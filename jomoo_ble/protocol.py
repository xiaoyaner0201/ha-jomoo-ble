"""Original, conservative codec for the JOMOO ZS800J BLE status/control protocol.

Every field mapping here is written from wire observations of the owner's device and
from independently documented behaviour (see docs/protocol.md). No vendor code is
included. Unknown bits are kept raw and never written with guessed values.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from enum import Enum
from typing import Mapping, Optional

HEADER = b"\xf3\xf4"
TRAILER = 0xFC
SOURCE = 0x92  # app / central
DEVICE = 0x21  # toilet main controller
BROADCAST = 0x00
SERVICE = "0000ffe0-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC = "0000ffe1-0000-1000-8000-00805f9b34fb"

STATE = 0xE2
FILTER = 0xE7
WORK = 0xE9
LID_RING = 0xEA
EXTENDED = 0xFA
OPTION = 0x1F
EXPECTED_LENGTHS = {STATE: 7, FILTER: 4, WORK: 6, LID_RING: 13, EXTENDED: 8}
FILTER_LIFE_MINUTES = 13980


class ProtocolError(ValueError):
    """A malformed frame or an unsafe/unsupported command request."""


@dataclass(frozen=True)
class Frame:
    source: int
    destination: int
    command: int
    payload: bytes

    def encode(self) -> bytes:
        return build_frame(self.command, self.payload, self.source, self.destination)


def checksum(body: bytes) -> int:
    """Sum LEN through the last payload byte (envelope and checksum excluded)."""
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
    return HEADER + body + bytes((checksum(body), TRAILER))


def parse_frame(data: bytes) -> Frame:
    data = bytes(data)
    if len(data) < 8 or data[:2] != HEADER or data[-1] != TRAILER:
        raise ProtocolError("Invalid frame envelope")
    if data[2] != len(data) - 4:
        raise ProtocolError("Length mismatch")
    if data[-2] != checksum(data[2:-2]):
        raise ProtocolError("Checksum mismatch")
    return Frame(data[3], data[4], data[5], data[6:-2])


class FrameDecoder:
    """Bounded notification-stream decoder; tolerates chunking and resynchronises."""

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
        return frames


def state_query() -> bytes:
    """Read-only status query (broadcast). The toilet answers with E2/EA/E9/FA."""
    return build_frame(STATE, bytes(4), destination=BROADCAST)


def filter_query() -> bytes:
    return build_frame(FILTER, bytes(4))


def validate_status(frame: Frame) -> None:
    if frame.source != DEVICE:
        raise ProtocolError("Not a toilet status frame")
    if frame.command not in EXPECTED_LENGTHS:
        raise ProtocolError("Unmapped response command")
    if len(frame.payload) != EXPECTED_LENGTHS[frame.command]:
        raise ProtocolError("Unmapped response layout")


def _bit(value: int, bit: int) -> bool:
    return bool((value >> bit) & 1)


def _require(frame: Frame, command: int) -> bytes:
    validate_status(frame)
    if frame.command != command:
        raise ProtocolError(f"Expected 0x{command:02X} frame")
    return frame.payload


# --------------------------------------------------------------------------- E2


@dataclass(frozen=True)
class Settings:
    """User settings carried in E2 (and mirrored in every control frame)."""

    water_temperature: int
    auto_cover: bool
    gesture: bool
    auto_flush: bool
    night_light: bool
    hip_nozzle: int
    seat_temperature: int
    auto_night_light: bool
    hip_pressure: int
    air_temperature: int
    lady_pressure: int
    lady_nozzle: int
    raw: bytes


def decode_settings(frame: Frame) -> Settings:
    p = _require(frame, STATE)
    return Settings(
        water_temperature=(p[0] >> 4) & 7,
        auto_cover=_bit(p[0], 3),
        gesture=_bit(p[0], 2),
        auto_flush=_bit(p[0], 1),
        night_light=_bit(p[0], 0),
        hip_nozzle=(p[1] >> 4) & 7,
        seat_temperature=p[1] & 0x0F,
        auto_night_light=_bit(p[2], 7),
        hip_pressure=(p[2] >> 4) & 7,
        air_temperature=p[2] & 7,
        lady_pressure=(p[3] >> 4) & 7,
        lady_nozzle=p[3] & 7,
        raw=p,
    )


# --------------------------------------------------------------------------- FA


class FoamLevel(str, Enum):
    LOW = "low"
    SUFFICIENT = "sufficient"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Extended:
    """Extended settings and live flags carried in FA."""

    water_temperature: int
    auto_cover: bool
    auto_flush: bool
    smart_power_save: bool
    hip_nozzle: int
    seat_temperature: int
    auto_night_light: bool
    hip_pressure: int
    air_temperature: int
    lady_pressure: int
    lady_nozzle: int
    large_flushing: bool
    small_flushing: bool
    close_lid_before_flush: bool
    auto_deodorization: bool
    wind_speed: int
    uv_disinfection: bool
    ambient_light: bool
    seasonal_temperature: bool
    ambient_light_mode: int
    add_liquid_box: bool
    pre_wetting: bool
    open_loop_foam: bool
    auto_foam: bool
    foam_running: bool
    filter_insufficient: bool
    filter_reminder: bool
    foam_level: FoamLevel
    foot_sensor: bool
    auto_small_flush: bool
    wide_wash_level: int
    raw: bytes

    @property
    def flushing(self) -> bool:
        return self.small_flushing or self.large_flushing


def decode_extended(frame: Frame) -> Extended:
    p = _require(frame, EXTENDED)
    foam_bits = (p[7] >> 6) & 3
    foam = {0: FoamLevel.LOW, 3: FoamLevel.SUFFICIENT}.get(foam_bits, FoamLevel.UNKNOWN)
    return Extended(
        water_temperature=(p[0] >> 4) & 7,
        auto_cover=_bit(p[0], 3),
        auto_flush=_bit(p[0], 1),
        smart_power_save=_bit(p[1], 7),
        hip_nozzle=(p[1] >> 4) & 7,
        seat_temperature=p[1] & 7,
        auto_night_light=_bit(p[2], 7),
        hip_pressure=(p[2] >> 4) & 7,
        air_temperature=p[2] & 7,
        lady_pressure=(p[3] >> 4) & 0x0F,
        lady_nozzle=p[3] & 0x0F,
        large_flushing=_bit(p[4], 3),
        small_flushing=_bit(p[4], 2),
        close_lid_before_flush=_bit(p[4], 1),
        auto_deodorization=_bit(p[4], 0),
        wind_speed=(p[4] >> 4) & 7,
        uv_disinfection=_bit(p[5], 5),
        ambient_light=_bit(p[5], 4),
        seasonal_temperature=_bit(p[5], 3),
        ambient_light_mode=(p[5] >> 6) & 3,
        add_liquid_box=_bit(p[6], 6),
        pre_wetting=_bit(p[6], 5),
        open_loop_foam=_bit(p[6], 4),
        auto_foam=_bit(p[6], 3),
        foam_running=_bit(p[6], 2),
        filter_insufficient=_bit(p[6], 1),
        filter_reminder=_bit(p[6], 0),
        foam_level=foam,
        foot_sensor=_bit(p[7], 5),
        auto_small_flush=_bit(p[7], 4),
        wide_wash_level=max(1, p[7] & 7),
        raw=p,
    )


# --------------------------------------------------------------------------- E9


class WorkStatus(str, Enum):
    STANDBY = "standby"
    NOZZLE_CLEANING = "nozzle_cleaning"
    NOZZLE_REPLACEMENT = "nozzle_replacement"
    DRYING = "drying"
    HIP_WASH = "hip_wash"
    LADY_WASH = "lady_wash"
    OTHER = "other"


def work_status(code: int) -> WorkStatus:
    if code in (1, 2):
        return WorkStatus.STANDBY
    if code == 3:
        return WorkStatus.NOZZLE_CLEANING
    if code == 0x83:
        return WorkStatus.NOZZLE_REPLACEMENT
    if code in (0x10, 0x90):
        return WorkStatus.DRYING
    if code & 0x20:
        return WorkStatus.HIP_WASH
    if code & 0x40:
        return WorkStatus.LADY_WASH
    return WorkStatus.OTHER


@dataclass(frozen=True)
class Runtime:
    seated: bool
    deodorizing: bool
    water_shortage: bool
    flow_abnormal: bool
    outlet_over_temperature: bool
    inlet_over_temperature: bool
    outlet_sensor_fault: bool
    inlet_sensor_fault: bool
    seat_over_temperature: bool
    seat_temperature_error: bool
    ambient_sensor_fault: bool
    work_code: int
    auto_mode: bool
    raw: bytes

    @property
    def status(self) -> WorkStatus:
        return work_status(self.work_code)

    @property
    def standby(self) -> bool:
        return self.status is WorkStatus.STANDBY

    @property
    def fault(self) -> bool:
        return any(
            (
                self.outlet_over_temperature,
                self.inlet_over_temperature,
                self.outlet_sensor_fault,
                self.inlet_sensor_fault,
                self.seat_over_temperature,
                self.seat_temperature_error,
                self.ambient_sensor_fault,
            )
        )


def decode_runtime(frame: Frame) -> Runtime:
    p = _require(frame, WORK)
    return Runtime(
        seated=_bit(p[0], 7),
        deodorizing=_bit(p[0], 5),
        water_shortage=_bit(p[1], 7),
        flow_abnormal=_bit(p[1], 6) or _bit(p[1], 3),
        outlet_over_temperature=_bit(p[1], 5),
        inlet_over_temperature=_bit(p[1], 4),
        outlet_sensor_fault=_bit(p[1], 2),
        inlet_sensor_fault=_bit(p[1], 0),
        seat_over_temperature=_bit(p[2], 5),
        seat_temperature_error=_bit(p[2], 1),
        ambient_sensor_fault=_bit(p[2], 0),
        work_code=p[3],
        auto_mode=_bit(p[4], 3),
        raw=p,
    )


# --------------------------------------------------------------------------- EA


@dataclass(frozen=True)
class Mechanism:
    lid_open: Optional[bool]
    ring_open: Optional[bool]
    lid_moving: bool
    ring_moving: bool
    raw: bytes

    @property
    def settled(self) -> bool:
        return (
            not self.lid_moving
            and not self.ring_moving
            and self.lid_open is not None
            and self.ring_open is not None
        )


_POSITION = {1: False, 2: True}  # two-bit state: 01 closed, 10 open, else in transit


def decode_mechanism(frame: Frame) -> Mechanism:
    p = _require(frame, LID_RING)
    flags = p[0]
    return Mechanism(
        lid_open=_POSITION.get((flags >> 2) & 3),
        ring_open=_POSITION.get(flags & 3),
        lid_moving=_bit(flags, 6),
        ring_moving=_bit(flags, 5),
        raw=p,
    )


# --------------------------------------------------------------------------- E7


@dataclass(frozen=True)
class FilterStatus:
    used_minutes: int

    @property
    def used_hours(self) -> float:
        return round(self.used_minutes / 60, 1)

    @property
    def remaining_percent(self) -> float:
        remaining = 100 * (FILTER_LIFE_MINUTES - self.used_minutes) / FILTER_LIFE_MINUTES
        return round(min(100.0, max(0.0, remaining)), 1)


def decode_filter(frame: Frame) -> FilterStatus:
    p = _require(frame, FILTER)
    hours = ((p[3] >> 6) << 8) | p[2]
    return FilterStatus(used_minutes=hours * 60 + (p[3] & 0x3F))


# ------------------------------------------------------------------- encoding


@dataclass(frozen=True)
class WritableSettings:
    """Every field the 19-byte function frame carries, taken from a fresh read."""

    water_temperature: int
    auto_cover: bool
    gesture: bool
    auto_flush: bool
    night_light: bool
    smart_power_save: bool
    hip_nozzle: int
    seat_temperature: int
    auto_night_light: bool
    hip_pressure: int
    air_temperature: int
    wide_wash_level: int
    wind_speed: int


# name -> (min, max). Booleans use (0, 1).
RANGES: Mapping[str, tuple[int, int]] = {
    "water_temperature": (0, 5),
    "seat_temperature": (0, 5),
    "air_temperature": (0, 4),
    "hip_pressure": (1, 5),
    "hip_nozzle": (1, 5),
    "wind_speed": (1, 5),
    "wide_wash_level": (1, 5),
    "auto_cover": (0, 1),
    "auto_flush": (0, 1),
    "auto_night_light": (0, 1),
}
READ_ONLY = frozenset(
    {"gesture", "night_light", "smart_power_save", "lady_pressure", "lady_nozzle"}
)
# Only this setting has been physically verified with full before/after read-back.
VERIFIED_SETTINGS = frozenset({"auto_cover"})


def writable_from(settings: Settings, extended: Extended) -> WritableSettings:
    """Combine a fresh E2 and FA; refuse if their shared fields disagree."""
    shared = (
        "water_temperature",
        "auto_cover",
        "auto_flush",
        "hip_nozzle",
        "auto_night_light",
        "hip_pressure",
        "air_temperature",
    )
    for name in shared:
        if getattr(settings, name) != getattr(extended, name):
            raise ProtocolError(f"E2/FA disagree on {name}; status is not settled")
    if (settings.seat_temperature & 7) != extended.seat_temperature:
        raise ProtocolError("E2/FA disagree on seat_temperature; status is not settled")
    return WritableSettings(
        water_temperature=settings.water_temperature,
        auto_cover=settings.auto_cover,
        gesture=settings.gesture,
        auto_flush=settings.auto_flush,
        night_light=settings.night_light,
        smart_power_save=extended.smart_power_save,
        hip_nozzle=settings.hip_nozzle,
        seat_temperature=settings.seat_temperature,
        auto_night_light=settings.auto_night_light,
        hip_pressure=settings.hip_pressure,
        air_temperature=settings.air_temperature,
        wide_wash_level=extended.wide_wash_level,
        wind_speed=extended.wind_speed,
    )


def with_changes(current: WritableSettings, changes: Mapping[str, int | bool]) -> WritableSettings:
    known = {f.name for f in fields(WritableSettings)}
    for name, value in changes.items():
        if name in READ_ONLY:
            raise ProtocolError(f"{name} is read-only")
        if name not in known or name not in RANGES:
            raise ProtocolError(f"{name} is not a writable setting")
        low, high = RANGES[name]
        if isinstance(value, bool):
            value = int(value)
        if type(value) is not int or not low <= value <= high:
            raise ProtocolError(f"{name} must be within {low}..{high}")
    normalised = {
        name: bool(value) if isinstance(getattr(current, name), bool) else int(value)
        for name, value in changes.items()
    }
    return replace(current, **normalised)


class Op(int, Enum):
    STOP = 0x00
    LARGE_FLUSH = 0x0E
    SMALL_FLUSH = 0x0F
    CLOSE_LID = 0x10
    OPEN_LID_RING_CLOSED = 0x11
    OPEN_RING = 0x13
    APPLY_SETTINGS = 0x19


def function_frame(op: Op, settings: WritableSettings) -> bytes:
    """Build the 19-byte function frame; every carried setting comes from `settings`."""
    if not isinstance(op, Op) or op is Op.STOP:
        raise ProtocolError("Unsupported function opcode")
    s = settings
    for name, (low, high) in RANGES.items():
        value = int(getattr(s, name))
        if not low <= value <= high:
            raise ProtocolError(f"Refusing to encode out-of-range {name}={value}")
    if not 0 <= s.seat_temperature <= 15:
        raise ProtocolError("seat_temperature out of range")
    b6 = (
        (s.water_temperature << 4)
        | (int(s.auto_cover) << 3)
        | (int(s.gesture) << 2)
        | (int(s.auto_flush) << 1)
        | int(s.night_light)
    )
    b7 = (int(s.smart_power_save) << 7) | (s.hip_nozzle << 4) | s.seat_temperature
    b8 = (int(s.auto_night_light) << 7) | (s.hip_pressure << 4) | s.air_temperature
    payload = bytes((b6, b7 & 0xFF, b8, s.wide_wash_level << 4, 0, s.wind_speed << 4)) + bytes(5)
    return build_frame(int(op), payload)


class Option(str, Enum):
    """Settings changed with the short 0x1F option frame (app-derived, unverified)."""

    UV_DISINFECTION = "uv_disinfection"
    CLOSE_LID_BEFORE_FLUSH = "close_lid_before_flush"
    AUTO_SMALL_FLUSH = "auto_small_flush"
    FOOT_SENSOR = "foot_sensor"
    AMBIENT_LIGHT = "ambient_light"


# option -> (sub-command, value when on, value when off)
OPTION_CODES: Mapping[Option, tuple[int, int, int]] = {
    Option.UV_DISINFECTION: (0x21, 0x40, 0x20),
    Option.CLOSE_LID_BEFORE_FLUSH: (0x25, 0x01, 0x02),
    Option.AUTO_SMALL_FLUSH: (0x25, 0x04, 0x08),
    Option.FOOT_SENSOR: (0x24, 0x01, 0x02),
    Option.AMBIENT_LIGHT: (0x33, 0x20, 0x10),
}


def option_frame(option: Option, enabled: bool) -> bytes:
    if not isinstance(option, Option):
        raise ProtocolError("Unsupported option")
    sub, on, off = OPTION_CODES[option]
    return build_frame(OPTION, bytes((sub, on if enabled else off)))


# Fields compared before/after every write to prove nothing else changed.
PRESERVED_SETTINGS = (
    "water_temperature",
    "auto_cover",
    "gesture",
    "auto_flush",
    "night_light",
    "hip_nozzle",
    "seat_temperature",
    "auto_night_light",
    "hip_pressure",
    "air_temperature",
    "lady_pressure",
    "lady_nozzle",
)
PRESERVED_EXTENDED = (
    "smart_power_save",
    "close_lid_before_flush",
    "auto_deodorization",
    "wind_speed",
    "uv_disinfection",
    "ambient_light",
    "seasonal_temperature",
    "ambient_light_mode",
    "pre_wetting",
    "open_loop_foam",
    "auto_foam",
    "filter_reminder",
    "foot_sensor",
    "auto_small_flush",
    "wide_wash_level",
)


def settings_diff(
    before: tuple[Settings, Extended],
    after: tuple[Settings, Extended],
    allowed: frozenset[str] = frozenset(),
) -> dict[str, tuple[object, object]]:
    diff: dict[str, tuple[object, object]] = {}
    for index, names in ((0, PRESERVED_SETTINGS), (1, PRESERVED_EXTENDED)):
        for name in names:
            if name in allowed:
                continue
            old, new = getattr(before[index], name), getattr(after[index], name)
            if old != new:
                diff[name] = (old, new)
    return diff
