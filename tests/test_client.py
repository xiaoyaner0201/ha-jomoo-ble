"""Synthetic BLE transport tests (no radio, no Home Assistant, no device)."""

import asyncio
import unittest
from dataclasses import dataclass, field

from jomoo_ble.client import (
    FLUSH_UNCONFIRMED,
    CommandRefused,
    Mechanical,
    SessionError,
    SessionManager,
    SetOption,
    SetSettings,
    VerificationError,
)
from jomoo_ble.protocol import Option, build_frame, parse_frame

E2 = bytes.fromhex("f3f40b2192e24a52b3450900003dfc")
FA = bytes.fromhex("f3f40c2100fa4a52b345113229335afc")
E9 = bytes.fromhex("f3f40a2100e94500000100005afc")
EA = bytes.fromhex("f3f4112122ea05008500804c13005f0000000006fc")
E7 = bytes.fromhex("f3f4082192e701c3131c95fc")


def with_byte(frame: bytes, index: int, value: int) -> bytes:
    """Return the frame with payload byte `index` replaced (checksum recomputed)."""
    parsed = parse_frame(frame)
    payload = bytearray(parsed.payload)
    payload[index] = value
    return build_frame(parsed.command, bytes(payload), parsed.source, parsed.destination)


@dataclass
class Device:
    """A tiny state machine standing in for the toilet."""

    e2: bytes = E2
    fa: bytes = FA
    e9: bytes = E9
    ea: bytes = EA
    flush_bit_on_flush: bool = True
    ignore_writes: bool = False
    corrupt_on_write: bool = False
    write_error: bool = False
    disconnect_error: bool = False
    stay_connected: bool = False
    drop_queries_after_write: int = 0
    active: int = 0
    max_active: int = 0
    connections: int = 0
    writes: list = field(default_factory=list)

    def apply(self, frame: bytes) -> None:
        parsed = parse_frame(frame)
        if self.ignore_writes:
            return
        if parsed.command == 0x19:
            b6 = parsed.payload[0]
            self.e2 = with_byte(self.e2, 0, b6)
            self.fa = with_byte(self.fa, 0, b6)
        elif parsed.command == 0x10:
            self.ea = with_byte(self.ea, 0, 0x05)
        elif parsed.command == 0x11:
            self.ea = with_byte(self.ea, 0, 0x09)
        elif parsed.command == 0x13:
            self.ea = with_byte(self.ea, 0, 0x0A)
        elif parsed.command in (0x0E, 0x0F) and self.flush_bit_on_flush:
            self.fa = with_byte(self.fa, 4, parse_frame(self.fa).payload[4] | 0x04)
        elif parsed.command == 0x1F and parsed.payload[0] == 0x21:
            p5 = parse_frame(self.fa).payload[5]
            p5 = p5 | 0x20 if parsed.payload[1] == 0x40 else p5 & ~0x20
            self.fa = with_byte(self.fa, 5, p5)
        elif parsed.command == 0x1F and parsed.payload[0] == 0x24:
            p7 = parse_frame(self.fa).payload[7]
            p7 = p7 | 0x20 if parsed.payload[1] == 0x01 else p7 & ~0x20
            self.fa = with_byte(self.fa, 7, p7)
        if self.corrupt_on_write:
            self.e2 = with_byte(self.e2, 1, 0x55)  # seat temperature 5 instead of 2
            self.fa = with_byte(self.fa, 1, 0x55)


class FakeClient:
    def __init__(self, device: Device):
        self.device = device
        self.callback = None
        self.is_connected = True

    async def start_notify(self, characteristic, callback):
        self.callback = callback

    async def write_gatt_char(self, characteristic, data, response):
        data = bytes(data)
        frame = parse_frame(data)
        await asyncio.sleep(0)
        if frame.command == 0xE2:
            if self.device.writes and self.device.drop_queries_after_write > 0:
                self.device.drop_queries_after_write -= 1
                for item in (self.device.ea, self.device.e9, self.device.fa):
                    self.callback(None, bytearray(item))
                return
            for item in (self.device.e2, self.device.ea, self.device.e9, self.device.fa):
                self.callback(None, bytearray(item))
            return
        if frame.command == 0xE7:
            self.callback(None, bytearray(E7))
            return
        self.device.writes.append(data)
        if self.device.write_error:
            raise OSError("synthetic lost acknowledgement")
        self.device.apply(data)

    async def disconnect(self):
        self.device.active -= 1
        if self.device.disconnect_error:
            raise OSError("synthetic disconnect failure")
        self.is_connected = self.device.stay_connected


def manager(device: Device) -> SessionManager:
    async def connect():
        device.connections += 1
        device.active += 1
        device.max_active = max(device.max_active, device.active)
        await asyncio.sleep(0)
        return FakeClient(device)

    return SessionManager(
        connect,
        response_timeout=0.2,
        action_timeout=0.3,
        flush_confirm_timeout=0.2,
        settle_time=0,
        poll_gap=0,
        resend_interval=0.03,
    )


def run(coro):
    return asyncio.run(coro)


class SessionTests(unittest.TestCase):
    def test_poll_reads_everything_and_disconnects(self):
        device = Device()
        snap = run(manager(device).poll())
        self.assertEqual(snap.settings.water_temperature, 4)
        self.assertEqual(snap.filter.remaining_percent, 91.6)
        self.assertEqual(device.active, 0)
        self.assertEqual(device.writes, [])

    def test_open_lid_then_already_open_is_noop(self):
        device = Device()
        session = manager(device)
        snap = run(session.command(Mechanical.OPEN_LID))
        self.assertTrue(snap.mechanism.lid_open)
        self.assertEqual(len(device.writes), 1)
        run(session.command(Mechanical.OPEN_LID))
        self.assertEqual(len(device.writes), 1)

    def test_auto_cover_off_verified(self):
        device = Device()
        snap = run(manager(device).command(SetSettings({"auto_cover": False})))
        self.assertFalse(snap.settings.auto_cover)
        self.assertEqual(device.writes[0].hex(), "f3f40f9221194252b3300010000000000062fc")

    def test_query_dropped_after_write_is_resent(self):
        device = Device(drop_queries_after_write=2)
        snap = run(manager(device).command(SetSettings({"auto_cover": False})))
        self.assertFalse(snap.settings.auto_cover)
        self.assertEqual(len(device.writes), 1)  # only the setting write, never retried

    def test_option_write(self):
        device = Device(fa=with_byte(FA, 5, 0x12))  # UV off
        snap = run(manager(device).command(SetOption(Option.UV_DISINFECTION, True)))
        self.assertTrue(snap.extended.uv_disinfection)

    def test_foot_sensor_round_trip_and_noop(self):
        device = Device()
        session = manager(device)
        for enabled, p7, value in ((False, 0x13, 0x02), (True, 0x33, 0x01)):
            with self.subTest(enabled=enabled):
                snap = run(session.command(SetOption(Option.FOOT_SENSOR, enabled)))
                self.assertEqual(snap.extended.foot_sensor, enabled)
                self.assertEqual(snap.extended.raw[7], p7)
                self.assertEqual(parse_frame(device.writes[-1]).payload, bytes((0x24, value)))
        self.assertEqual(len(device.writes), 2)
        run(session.command(SetOption(Option.FOOT_SENSOR, True)))
        self.assertEqual(len(device.writes), 2)

    def test_foot_sensor_keeps_write_safety_guarantees(self):
        for device, error in (
            (Device(write_error=True), SessionError),
            (Device(ignore_writes=True), VerificationError),
            (Device(corrupt_on_write=True), VerificationError),
        ):
            with self.subTest(error=error):
                with self.assertRaises(error):
                    run(manager(device).command(SetOption(Option.FOOT_SENSOR, False)))
                self.assertEqual(len(device.writes), 1)
                self.assertEqual(device.active, 0)

    def test_refuse_when_busy_seated_or_moving(self):
        cases = {
            "busy": Device(e9=with_byte(E9, 3, 0x20)),
            "seated": Device(e9=with_byte(E9, 0, 0xC5)),
            "moving": Device(ea=with_byte(EA, 0, 0x45)),
            "transit": Device(ea=with_byte(EA, 0, 0xD0)),
        }
        for name, device in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(CommandRefused):
                    run(manager(device).command(Mechanical.SMALL_FLUSH))
                self.assertEqual(device.writes, [])
                self.assertEqual(device.active, 0)

    def test_busy_refuses_settings_too(self):
        device = Device(e9=with_byte(E9, 3, 0x03))
        with self.assertRaises(CommandRefused):
            run(manager(device).command(SetSettings({"auto_cover": False})))

    def test_unrelated_change_raises_diff(self):
        device = Device(corrupt_on_write=True)
        with self.assertRaises(VerificationError) as ctx:
            run(manager(device).command(Mechanical.OPEN_LID))
        self.assertIn("seat_temperature", ctx.exception.diff)

    def test_unconfirmed_action(self):
        device = Device(ignore_writes=True)
        with self.assertRaises(VerificationError):
            run(manager(device).command(Mechanical.OPEN_RING))
        self.assertEqual(len(device.writes), 1)

    def test_flush_confirmed_and_unconfirmed(self):
        snap = run(manager(Device()).command(Mechanical.SMALL_FLUSH))
        self.assertIsNone(snap.warning)
        device = Device(flush_bit_on_flush=False)
        snap = run(manager(device).command(Mechanical.SMALL_FLUSH))
        self.assertEqual(snap.warning, FLUSH_UNCONFIRMED)
        self.assertEqual(len(device.writes), 1)

    def test_no_retry_after_write_error(self):
        device = Device(write_error=True)
        with self.assertRaises(SessionError):
            run(manager(device).command(Mechanical.OPEN_LID))
        self.assertEqual(len(device.writes), 1)
        self.assertEqual(device.active, 0)

    def test_missing_frames(self):
        device = Device()

        class Silent(FakeClient):
            async def write_gatt_char(self, characteristic, data, response):
                return None

        async def connect():
            device.active += 1
            return Silent(device)

        session = SessionManager(connect, response_timeout=0.05, settle_time=0)
        with self.assertRaises(SessionError):
            run(session.poll())
        self.assertEqual(device.active, 0)

    def test_disconnect_uncertainty_blocks(self):
        device = Device(stay_connected=True)
        session = manager(device)

        async def scenario():
            with self.assertRaises(SessionError):
                await session.poll()
            with self.assertRaises(SessionError):
                await session.poll()

        run(scenario())
        self.assertEqual(device.connections, 1)

    def test_lock_serializes(self):
        device = Device()
        session = manager(device)

        async def scenario():
            await asyncio.gather(
                session.poll(),
                session.command(Mechanical.OPEN_LID),
                session.command(SetSettings({"auto_cover": False})),
            )

        run(scenario())
        self.assertEqual(device.max_active, 1)
        self.assertEqual(device.connections, 3)


if __name__ == "__main__":
    unittest.main()
