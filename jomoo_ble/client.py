"""Serialized, short-lived BLE sessions, independent of Home Assistant.

Every connection makes the toilet beep and only one central may be connected, so
each operation is connect -> fresh query -> (write -> verify) -> disconnect under a
single lock. Actuator writes are never retried automatically. The connector is
injected; tests never touch a radio.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Awaitable, Callable, Mapping, Optional, Protocol, Union

from .protocol import (
    CHARACTERISTIC,
    EXTENDED,
    FILTER,
    LID_RING,
    STATE,
    WORK,
    Extended,
    FilterStatus,
    Frame,
    FrameDecoder,
    Mechanism,
    Op,
    Option,
    ProtocolError,
    Runtime,
    Settings,
    decode_extended,
    decode_filter,
    decode_mechanism,
    decode_runtime,
    decode_settings,
    filter_query,
    function_frame,
    option_frame,
    settings_diff,
    state_query,
    validate_status,
    with_changes,
    writable_from,
)

REQUIRED = (STATE, LID_RING, WORK, EXTENDED)


class Client(Protocol):
    @property
    def is_connected(self) -> bool: ...

    async def start_notify(self, characteristic: str, callback: Callable) -> None: ...
    async def write_gatt_char(self, characteristic: str, data: bytes, response: bool) -> None: ...
    async def disconnect(self) -> None: ...


class SessionError(RuntimeError):
    """No reliable read-back, a refused command, or an uncertain connection state."""


class CommandRefused(SessionError):
    """The device state makes the requested command unsafe; nothing was written."""


class VerificationError(SessionError):
    """The write was sent but the device did not confirm the expected outcome."""

    def __init__(self, message: str, diff: Optional[Mapping[str, tuple]] = None) -> None:
        super().__init__(message)
        self.diff = dict(diff or {})


@dataclass(frozen=True)
class Snapshot:
    frames: Mapping[int, Frame]
    warning: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "frames", MappingProxyType(dict(self.frames)))

    def _decode(self, command: int, decoder):
        frame = self.frames.get(command)
        if frame is None:
            return None
        try:
            return decoder(frame)
        except ProtocolError:
            return None

    @property
    def settings(self) -> Optional[Settings]:
        return self._decode(STATE, decode_settings)

    @property
    def extended(self) -> Optional[Extended]:
        return self._decode(EXTENDED, decode_extended)

    @property
    def runtime(self) -> Optional[Runtime]:
        return self._decode(WORK, decode_runtime)

    @property
    def mechanism(self) -> Optional[Mechanism]:
        return self._decode(LID_RING, decode_mechanism)

    @property
    def filter(self) -> Optional[FilterStatus]:
        return self._decode(FILTER, decode_filter)


def _full(snap: Snapshot) -> tuple[Settings, Extended, Runtime, Mechanism]:
    settings, extended = snap.settings, snap.extended
    runtime, mechanism = snap.runtime, snap.mechanism
    if settings is None or extended is None or runtime is None or mechanism is None:
        raise SessionError("Status frames did not decode")
    return settings, extended, runtime, mechanism


class Mechanical(str, Enum):
    OPEN_LID = "open_lid"
    CLOSE_LID = "close_lid"
    OPEN_RING = "open_ring"
    CLOSE_RING = "close_ring"
    SMALL_FLUSH = "small_flush"
    LARGE_FLUSH = "large_flush"


@dataclass(frozen=True)
class SetSettings:
    changes: Mapping[str, Union[int, bool]]


@dataclass(frozen=True)
class SetOption:
    option: Option
    enabled: bool


Command = Union[Mechanical, SetSettings, SetOption]
# Called with the fresh pre-write snapshot inside the same connection; returning
# False skips the write (the snapshot is still returned).
Prepare = Callable[[Snapshot], Awaitable[bool]]

FLUSHES = (Mechanical.SMALL_FLUSH, Mechanical.LARGE_FLUSH)
FLUSH_UNCONFIRMED = "flush_sent_unconfirmed"


@dataclass
class _Window:
    frames: dict = field(default_factory=dict)
    event: asyncio.Event = field(default_factory=asyncio.Event)


class SessionManager:
    """One lock for refreshes, commands and shutdown; no actuator write retries."""

    def __init__(
        self,
        connect: Callable[[], Awaitable[Client]],
        response_timeout: float = 8.0,
        action_timeout: float = 15.0,
        flush_confirm_timeout: float = 6.0,
        settle_time: float = 0.4,
        poll_gap: float = 0.4,
        resend_interval: float = 2.0,
    ) -> None:
        self._connect = connect
        self._lock = asyncio.Lock()
        self._closed = False
        self._blocked = False
        self.response_timeout = response_timeout
        self.action_timeout = action_timeout
        self.flush_confirm_timeout = flush_confirm_timeout
        self.settle_time = settle_time
        self.poll_gap = poll_gap
        self.resend_interval = resend_interval

    @property
    def blocked(self) -> bool:
        return self._blocked

    async def close(self) -> None:
        self._closed = True
        async with self._lock:
            pass

    async def poll(self) -> Snapshot:
        return await self._run(None, None)

    async def command(self, command: Command, prepare: Optional[Prepare] = None) -> Snapshot:
        return await self._run(command, prepare)

    # ------------------------------------------------------------------ internals

    async def _run(self, command: Optional[Command], prepare: Optional[Prepare]) -> Snapshot:
        async with self._lock:
            if self._closed or self._blocked:
                raise SessionError("Session closed or disconnect uncertain; reload required")
            client = await self._connect()
            window = _Window()
            decoder = FrameDecoder()

            def notification(_sender: object, data: bytearray) -> None:
                for frame in decoder.feed(bytes(data)):
                    try:
                        validate_status(frame)
                    except ProtocolError:
                        continue
                    window.frames[frame.command] = frame
                    window.event.set()

            try:
                await asyncio.wait_for(client.start_notify(CHARACTERISTIC, notification), 10)
                before = await self._query(client, window, include_filter=True)
                if command is None:
                    return before
                if prepare is not None and not await prepare(before):
                    return before
                return await self._execute(client, window, command, before)
            finally:
                await self._disconnect(client)

    async def _query(
        self, client: Client, window: _Window, include_filter: bool = False
    ) -> Snapshot:
        window.frames.clear()
        window.event.clear()
        await client.write_gatt_char(CHARACTERISTIC, state_query(), response=False)
        if include_filter:
            await client.write_gatt_char(CHARACTERISTIC, filter_query(), response=False)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.response_timeout
        resend_at = loop.time() + self.resend_interval
        while not all(c in window.frames for c in REQUIRED):
            now = loop.time()
            remaining = deadline - now
            if remaining <= 0:
                missing = [f"0x{c:02X}" for c in REQUIRED if c not in window.frames]
                raise SessionError("Fresh status incomplete: missing " + ", ".join(missing))
            if now >= resend_at:
                # The toilet can drop a query that arrives while it is applying a
                # write; asking again is read-only and safe.
                await client.write_gatt_char(CHARACTERISTIC, state_query(), response=False)
                resend_at = now + self.resend_interval
            try:
                await asyncio.wait_for(window.event.wait(), min(remaining, resend_at - now))
            except asyncio.TimeoutError:
                continue
            window.event.clear()
        # E7 and late duplicates may trail the required burst.
        await asyncio.sleep(self.settle_time)
        snapshot = Snapshot(dict(window.frames))
        _full(snapshot)
        return snapshot

    def _plan(self, command: Command, before: Snapshot) -> tuple[Optional[bytes], frozenset]:
        settings, extended, runtime, mechanism = _full(before)
        if not runtime.standby:
            raise CommandRefused(f"Toilet is busy ({runtime.status.value}); command refused")
        current = writable_from(settings, extended)
        if isinstance(command, Mechanical):
            if runtime.seated:
                raise CommandRefused("Seat is occupied; command refused")
            if not mechanism.settled:
                raise CommandRefused("Lid/ring moving or position unknown; command refused")
            if command is Mechanical.OPEN_LID:
                if mechanism.lid_open:
                    return None, frozenset()  # 0x11 would also close an open ring
                op = Op.OPEN_LID_RING_CLOSED
            elif command is Mechanical.CLOSE_RING:
                if not mechanism.ring_open:
                    return None, frozenset()
                op = Op.OPEN_LID_RING_CLOSED
            elif command is Mechanical.OPEN_RING:
                if mechanism.ring_open:
                    return None, frozenset()
                op = Op.OPEN_RING
            elif command is Mechanical.CLOSE_LID:
                if not mechanism.lid_open:
                    return None, frozenset()
                op = Op.CLOSE_LID
            elif command is Mechanical.SMALL_FLUSH:
                op = Op.SMALL_FLUSH
            elif command is Mechanical.LARGE_FLUSH:
                op = Op.LARGE_FLUSH
            else:  # pragma: no cover - exhaustive enum
                raise CommandRefused("Unsupported command")
            return function_frame(op, current), frozenset()
        if isinstance(command, SetSettings):
            target = with_changes(current, command.changes)
            changed = frozenset(
                k for k in command.changes if getattr(current, k) != getattr(target, k)
            )
            if not changed:
                return None, frozenset()
            return function_frame(Op.APPLY_SETTINGS, target), changed
        if isinstance(command, SetOption):
            if getattr(extended, command.option.value) == command.enabled:
                return None, frozenset()
            return option_frame(command.option, command.enabled), frozenset({command.option.value})
        raise CommandRefused("Unsupported command")

    def _reached(self, command: Command, snap: Snapshot) -> bool:
        if isinstance(command, Mechanical):
            m = snap.mechanism
            if m is None or not m.settled:
                return False
            return {
                Mechanical.OPEN_LID: m.lid_open is True,
                Mechanical.CLOSE_LID: m.lid_open is False,
                Mechanical.OPEN_RING: m.ring_open is True,
                Mechanical.CLOSE_RING: m.ring_open is False,
            }[command]
        settings, extended, _, _ = _full(snap)
        if isinstance(command, SetSettings):
            current = writable_from(settings, extended)
            target = with_changes(current, command.changes)
            return current == target
        if isinstance(command, SetOption):
            return getattr(extended, command.option.value) == command.enabled
        return False

    async def _execute(
        self, client: Client, window: _Window, command: Command, before: Snapshot
    ) -> Snapshot:
        packet, allowed = self._plan(command, before)
        if packet is None:
            return before  # already in the requested state; nothing written
        try:
            await asyncio.wait_for(
                client.write_gatt_char(CHARACTERISTIC, packet, response=False), 10
            )
        except Exception as err:
            # The packet may still have reached the device. Never retry.
            raise SessionError("Write failed; device state unknown, not retried") from err

        loop = asyncio.get_running_loop()
        if command in FLUSHES:
            after = await self._await_flush(client, window, before)
        else:
            deadline = loop.time() + self.action_timeout
            while True:
                after = await self._query(client, window)
                if self._reached(command, after):
                    break
                if loop.time() >= deadline:
                    raise VerificationError("Command not confirmed by device status")
                await asyncio.sleep(self.poll_gap)
        b_settings, b_extended, _, _ = _full(before)
        a_settings, a_extended, _, _ = _full(after)
        diff = settings_diff((b_settings, b_extended), (a_settings, a_extended), allowed)
        if diff:
            raise VerificationError("Unrelated settings changed after the write", diff)
        return after

    async def _await_flush(self, client: Client, window: _Window, before: Snapshot) -> Snapshot:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.flush_confirm_timeout
        last = before
        while loop.time() < deadline:
            # Pushed FA frames may already show the flush; otherwise ask again.
            pushed = window.frames.get(EXTENDED)
            if pushed is not None:
                try:
                    if decode_extended(pushed).flushing:
                        return await self._query(client, window)
                except ProtocolError:
                    pass
            last = await self._query(client, window)
            if _full(last)[1].flushing:
                return last
            await asyncio.sleep(self.poll_gap)
        return Snapshot(dict(last.frames), warning=FLUSH_UNCONFIRMED)

    async def _disconnect(self, client: Client) -> None:
        async def disconnect() -> None:
            try:
                await asyncio.wait_for(client.disconnect(), 5)
                if client.is_connected:
                    raise SessionError("Disconnect did not release the connection")
            except BaseException:
                self._blocked = True
                raise

        cleanup = asyncio.ensure_future(disconnect())
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await cleanup
            raise
