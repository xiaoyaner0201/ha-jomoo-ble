"""Serialized, short-lived BLE sessions, independent of Home Assistant.

The connector is injected; tests never open a radio or contact a proxy.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import MappingProxyType
from typing import Awaitable, Callable, Mapping, Protocol

from .protocol import (
    Action,
    CHARACTERISTIC,
    Frame,
    FrameDecoder,
    LID_RING,
    ProtocolError,
    STATE,
    action_complete,
    filter_query,
    mechanism,
    parameter_command,
    state_query,
    validate_status,
)


class Client(Protocol):
    @property
    def is_connected(self) -> bool: ...

    async def start_notify(self, characteristic: str, callback: Callable) -> None: ...
    async def write_gatt_char(self, characteristic: str, data: bytes, response: bool) -> None: ...
    async def disconnect(self) -> None: ...


@dataclass(frozen=True)
class Snapshot:
    frames: Mapping[int, Frame]

    def __post_init__(self) -> None:
        object.__setattr__(self, "frames", MappingProxyType(dict(self.frames)))


class SessionError(RuntimeError):
    """No reliable read-back or connection lifecycle."""


class SessionManager:
    """One lock for polls/commands/shutdown, no actuator write retries."""

    def __init__(
        self,
        connect: Callable[[], Awaitable[Client]],
        response_timeout: float = 8.0,
        action_timeout: float = 15.0,
        settle_time: float = 0.5,
    ) -> None:
        self._connect = connect
        self._lock = asyncio.Lock()
        self._closed = False
        self._blocked = False
        self.response_timeout = response_timeout
        self.action_timeout = action_timeout
        self.settle_time = settle_time

    async def close(self) -> None:
        self._closed = True
        # Drain the active bounded session and let its finally disconnect.
        async with self._lock:
            pass

    async def poll(self) -> Snapshot:
        return await self._run(None)

    async def command(self, action: Action) -> Snapshot:
        return await self._run(action)

    async def _run(self, action: Action | None) -> Snapshot:
        async with self._lock:
            if self._closed or self._blocked:
                raise SessionError("Session closed or disconnect uncertain; reload required")
            client = await self._connect()
            frames: dict[int, Frame] = {}
            decoder = FrameDecoder()
            event = asyncio.Event()

            def notification(_sender: object, data: bytearray) -> None:
                for frame in decoder.feed(data):
                    try:
                        validate_status(frame)
                    except ProtocolError:
                        continue
                    frames[frame.command] = frame
                    event.set()

            async def query(include_filter: bool = False) -> None:
                # No stale connection snapshot may satisfy the new query.
                frames.clear()
                event.clear()
                await client.write_gatt_char(CHARACTERISTIC, state_query(), response=False)
                if include_filter:
                    await client.write_gatt_char(CHARACTERISTIC, filter_query(), response=False)
                deadline = asyncio.get_running_loop().time() + self.response_timeout
                while STATE not in frames or LID_RING not in frames:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise SessionError("Fresh E2 and EA status required")
                    await asyncio.wait_for(event.wait(), remaining)
                    event.clear()
                # E7/FA/E9 may follow E2/EA and are optional, never invented.
                await asyncio.sleep(self.settle_time)

            try:
                await asyncio.wait_for(client.start_notify(CHARACTERISTIC, notification), 10)
                await asyncio.wait_for(query(include_filter=True), self.response_timeout + 5)
                if action is not None:
                    state = mechanism(frames[LID_RING])
                    if state.lid_moving or state.ring_moving:
                        raise SessionError("Mechanism moving; action refused")
                    if state.lid_open is None or state.ring_open is None:
                        raise SessionError("Unknown mechanism position; action refused")
                    # Opcode 0x11 selects lid-open/ring-closed. Do not close an
                    # already-open ring merely to satisfy an open-lid request.
                    if action == Action.OPEN_LID and state.lid_open:
                        return Snapshot(dict(frames))
                    if action == Action.CLOSE_RING and not state.ring_open:
                        return Snapshot(dict(frames))
                    packet = parameter_command(action, frames[STATE])
                    await asyncio.wait_for(
                        client.write_gatt_char(CHARACTERISTIC, packet, response=False), 10
                    )
                    # No retry: a failed write can still have reached the device.
                    deadline = asyncio.get_running_loop().time() + self.action_timeout
                    while True:
                        await asyncio.wait_for(query(), self.response_timeout + 5)
                        if action_complete(action, frames):
                            break
                        if asyncio.get_running_loop().time() >= deadline:
                            raise SessionError("Action not confirmed by device status")
                        await asyncio.sleep(0.25)
                return Snapshot(dict(frames))
            finally:

                async def disconnect() -> None:
                    try:
                        await asyncio.wait_for(client.disconnect(), 5)
                        if client.is_connected:
                            raise SessionError("Disconnect did not release the connection")
                    except BaseException:
                        self._blocked = True
                        raise

                cleanup = asyncio.create_task(disconnect())
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    await cleanup
                    raise
