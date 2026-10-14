"""Original, conservative F3/F4 codec derived from observed wire frames.

No vendor source is included. The parameter encoder intentionally accepts only
an empirically verified full settings profile; unmapped variants fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

HEADER = b"\xf3\xf4"
SOURCE = 0x92
DEVICE = 0x21
STATE = 0xE2
FILTER = 0xE7
LID_RING = 0xEA
WORK = 0xE9
EXTENDED = 0xFA
CHARACTERISTIC = "0000ffe1-0000-1000-8000-00805f9b34fb"
SERVICE = "0000ffe0-0000-1000-8000-00805f9b34fb"
EXPECTED_LENGTHS = {STATE: 7, FILTER: 4, LID_RING: 13, WORK: 6, EXTENDED: 8}
# EA/E9/E7 are also emitted to other controllers during an E2 query.
OBSERVED_DESTINATIONS = frozenset((SOURCE, 0x00, 0x22, 0x3A))


class ProtocolError(ValueError):
    """A malformed frame or an unsafe command request."""


@dataclass(frozen=True)
class Frame:
    source: int
    destination: int
    command: int
    payload: bytes

    def encode(self) -> bytes:
        return build_frame(self.command, self.payload, self.source, self.destination)


def checksum(body: bytes) -> int:
    """Sum LEN through the last payload byte, excluding envelope/checksum."""
    return sum(body) & 0xFF


def build_frame(
    command: int, payload: bytes | bytearray, source: int = SOURCE, destination: int = DEVICE
) -> bytes:
    if any(type(n) is not int or not 0 <= n <= 255 for n in (command, source, destination)):
        raise ProtocolError("Header fields must be bytes")
    payload = bytes(payload)
    if len(payload) > 251:
        raise ProtocolError("Payload exceeds one-byte length")
    body = bytes((len(payload) + 4, source, destination, command)) + payload
    return HEADER + body + bytes((checksum(body), 0xFC))


def parse_frame(data: bytes) -> Frame:
    data = bytes(data)
    if len(data) < 8 or data[:2] != HEADER or data[-1] != 0xFC:
        raise ProtocolError("Invalid frame envelope")
    if data[2] != len(data) - 4:
        raise ProtocolError("Length mismatch")
    if data[-2] != checksum(data[2:-2]):
        raise ProtocolError("Checksum mismatch")
    return Frame(data[3], data[4], data[5], data[6:-2])


class FrameDecoder:
    """Bounded notification stream decoder; handles chunks and resynchronization."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[Frame]:
        self._buffer.extend(chunk)
        frames = []
        while len(self._buffer) >= 2:
            index = self._buffer.find(HEADER)
            if index < 0:
                self._buffer[:] = b"\xf3" if self._buffer[-1] == 0xF3 else b""
                break
            del self._buffer[:index]
            if len(self._buffer) < 3:
                break
            length = self._buffer[2] + 4
            if length < 8:
                del self._buffer[0]
                continue
            if len(self._buffer) < length:
                break
            try:
                frame = parse_frame(self._buffer[:length])
            except ProtocolError:
                del self._buffer[0]
            else:
                frames.append(frame)
                del self._buffer[:length]
        # An incomplete valid-size candidate can hold at most 258 bytes.
        return frames


def state_query() -> bytes:
    """Read-only semantic query transported by an FFE1 write."""
    return build_frame(STATE, bytes(4), destination=0x00)


def filter_query() -> bytes:
    return build_frame(FILTER, bytes(4))


def validate_status(frame: Frame) -> None:
    if frame.source != DEVICE or frame.destination not in OBSERVED_DESTINATIONS:
        raise ProtocolError("Not a device status response")
    if frame.command not in EXPECTED_LENGTHS:
        raise ProtocolError("Unmapped response command")
    if len(frame.payload) != EXPECTED_LENGTHS[frame.command]:
        raise ProtocolError("Unmapped response layout")


@dataclass(frozen=True)
class Mechanism:
    lid_open: bool | None
    ring_open: bool | None
    lid_moving: bool
    ring_moving: bool


def mechanism(frame: Frame) -> Mechanism:
    validate_status(frame)
    if frame.command != LID_RING:
        raise ProtocolError("EA required for ZS800J mechanism status")
    flags = frame.payload[0]
    # Two-bit states: 1 closed, 2 open. 0/3 are not assigned a position.
    position = {1: False, 2: True}
    return Mechanism(
        position.get((flags >> 2) & 3),
        position.get(flags & 3),
        bool(flags & 0x40),
        bool(flags & 0x20),
    )


# Complete E2 profiles paired with physically verified parameter commands.
# Auto-cover is the only changed bit. Any other byte/bit change needs evidence.
PROFILE_OFF = bytes.fromhex("4252b345090000")
PROFILE_ON = bytes.fromhex("4a52b345090000")
PARAMETER_OFF = bytes.fromhex("4252b33000100000000000")
PARAMETER_ON = bytes.fromhex("4a52b33000100000000000")
VERIFIED_SETTINGS = {
    "water_temperature_level": 4,
    "seat_temperature_level": 2,
    "air_temperature_level": 3,
    "hip_water_pressure": 3,
    "hip_nozzle_position": 5,
    "woman_water_pressure": 4,
    "woman_nozzle_position": 5,
    "auto_flush": True,
}


def settings(frame: Frame) -> dict[str, int | bool]:
    validate_status(frame)
    if frame.command != STATE:
        raise ProtocolError("E2 required for parameter status")
    if frame.payload not in (PROFILE_OFF, PROFILE_ON):
        raise ProtocolError("Unmapped settings profile; writes refused")
    return {**VERIFIED_SETTINGS, "auto_cover": frame.payload == PROFILE_ON}


class Action(str, Enum):
    OPEN_LID = "open_lid"
    CLOSE_LID = "close_lid"
    OPEN_RING = "open_ring"
    CLOSE_RING = "close_ring"
    SMALL_FLUSH = "small_flush"
    AUTO_COVER_ON = "auto_cover_on"
    AUTO_COVER_OFF = "auto_cover_off"


OPCODES = {
    Action.OPEN_LID: 0x11,
    Action.CLOSE_LID: 0x10,
    Action.OPEN_RING: 0x13,
    # 0x11 closes the ring while leaving the lid open; it is not a typo.
    Action.CLOSE_RING: 0x11,
    Action.SMALL_FLUSH: 0x0F,
    Action.AUTO_COVER_ON: 0x19,
    Action.AUTO_COVER_OFF: 0x19,
}


def parameter_command(action: Action, current: Frame) -> bytes:
    """Build the verified 19-byte parameter frame, or refuse unknown fields.

    This API does not establish freshness: the session client must obtain E2 in
    the same locked connection immediately before calling it.
    """
    if not isinstance(action, Action):
        raise ProtocolError("Only explicitly supported actions may be written")
    observed = settings(current)
    enabled = observed["auto_cover"]
    if action == Action.AUTO_COVER_ON:
        enabled = True
    elif action == Action.AUTO_COVER_OFF:
        enabled = False
    payload = PARAMETER_ON if enabled else PARAMETER_OFF
    return build_frame(OPCODES[action], payload)


def action_complete(action: Action, frames: Mapping[int, Frame]) -> bool:
    if action in (Action.AUTO_COVER_OFF, Action.AUTO_COVER_ON):
        state = frames.get(STATE)
        return state is not None and settings(state)["auto_cover"] == (
            action == Action.AUTO_COVER_ON
        )
    if action == Action.SMALL_FLUSH:
        # A status response is NOT a physical flush acknowledgement.
        return STATE in frames and LID_RING in frames
    ea = frames.get(LID_RING)
    if ea is None:
        return False
    value = mechanism(ea)
    if value.lid_moving or value.ring_moving:
        return False
    return {
        Action.OPEN_LID: value.lid_open is True,
        Action.CLOSE_LID: value.lid_open is False,
        Action.OPEN_RING: value.ring_open is True,
        Action.CLOSE_RING: value.ring_open is False,
    }[action]
