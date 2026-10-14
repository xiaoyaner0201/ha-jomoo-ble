"""Protocol tests use anonymised wire fixtures observed on a real ZS800J."""

import unittest
from dataclasses import replace

from jomoo_ble.protocol import (
    FoamLevel,
    FrameDecoder,
    Op,
    Option,
    ProtocolError,
    WorkStatus,
    build_frame,
    decode_extended,
    decode_filter,
    decode_mechanism,
    decode_runtime,
    decode_settings,
    filter_query,
    function_frame,
    option_frame,
    parse_frame,
    settings_diff,
    state_query,
    validate_status,
    with_changes,
    work_status,
    writable_from,
)


def f(h):
    return parse_frame(bytes.fromhex(h))


E2_ON = "f3f40b2192e24a52b3450900003dfc"
E2_OFF = "f3f40b2192e24252b34509000035fc"
FA_ON = "f3f40c2100fa4a52b345113229335afc"
FA_ON_B = "f3f40c2100fa4a52b345113329335bfc"
FA_OFF = "f3f40c2100fa4252b3451132293352fc"
FA_FLUSHING = "f3f40c2100fa4a52b345153229335efc"
E9_STANDBY = "f3f40a2100e94500000100005afc"
E9_FIXTURES = (
    E9_STANDBY,
    "f3f40a2100e94d000001000062fc",
    "f3f40a2100e94c0000010080e1fc",
    "f3f40a2122e94400000100007bfc",
)
EA_CLOSED = "f3f4112122ea05008500804c13005f0000000006fc"
EA_LID_OPEN = "f3f4112122ea19008500804c13005f000000001afc"
EA_BOTH_OPEN = "f3f4112122ea1a008500804c13005f000000001bfc"
E7 = "f3f4082192e701c3131c95fc"

VECTORS = {
    Op.OPEN_LID_RING_CLOSED: "f3f40f9221114a52b3300010000000000062fc",
    Op.CLOSE_LID: "f3f40f9221104a52b3300010000000000061fc",
    Op.OPEN_RING: "f3f40f9221134a52b3300010000000000064fc",
    Op.SMALL_FLUSH: "f3f40f92210f4a52b3300010000000000060fc",
}
AUTO_COVER_OFF = "f3f40f9221194252b3300010000000000062fc"
AUTO_COVER_ON = "f3f40f9221194a52b330001000000000006afc"


def current(e2=E2_ON, fa=FA_ON):
    return writable_from(decode_settings(f(e2)), decode_extended(f(fa)))


class FrameTests(unittest.TestCase):
    def test_queries(self):
        self.assertEqual(state_query().hex(), "f3f4089200e2000000007cfc")
        self.assertEqual(filter_query().hex(), "f3f4089221e700000000a2fc")

    def test_every_fixture_round_trips_and_validates(self):
        for h in (
            E2_ON,
            E2_OFF,
            FA_ON,
            FA_ON_B,
            FA_OFF,
            FA_FLUSHING,
            EA_CLOSED,
            EA_LID_OPEN,
            EA_BOTH_OPEN,
            E7,
            *E9_FIXTURES,
        ):
            with self.subTest(h=h):
                frame = f(h)
                validate_status(frame)
                self.assertEqual(frame.encode().hex(), h)

    def test_malformed(self):
        good = bytes.fromhex(E2_ON)
        for bad in (
            good[:-1],
            b"\x00" + good[1:],
            good[:2] + b"\x09" + good[3:],
            good[:-2] + bytes([good[-2] ^ 1]) + good[-1:],
        ):
            with self.subTest(bad=bad.hex()), self.assertRaises(ProtocolError):
                parse_frame(bad)
        with self.assertRaises(ProtocolError):
            build_frame(256, b"")
        with self.assertRaises(ProtocolError):
            validate_status(parse_frame(build_frame(0xE2, bytes(7), source=0x92)))
        with self.assertRaises(ProtocolError):
            validate_status(parse_frame(build_frame(0xE2, bytes(3), source=0x21)))

    def test_decoder_chunking_and_resync(self):
        stream = b"\x00\xf3junk" + bytes.fromhex(E2_ON) + bytes.fromhex(EA_CLOSED)
        decoder = FrameDecoder()
        out = []
        for i in range(0, len(stream), 5):
            out += decoder.feed(stream[i : i + 5])
        self.assertEqual([x.command for x in out], [0xE2, 0xEA])


class DecodeTests(unittest.TestCase):
    def test_e2(self):
        s = decode_settings(f(E2_ON))
        self.assertEqual(
            (
                s.water_temperature,
                s.auto_cover,
                s.gesture,
                s.auto_flush,
                s.night_light,
                s.hip_nozzle,
                s.seat_temperature,
                s.auto_night_light,
                s.hip_pressure,
                s.air_temperature,
                s.lady_pressure,
                s.lady_nozzle,
            ),
            (4, True, False, True, False, 5, 2, True, 3, 3, 4, 5),
        )
        self.assertFalse(decode_settings(f(E2_OFF)).auto_cover)

    def test_fa(self):
        x = decode_extended(f(FA_ON))
        self.assertEqual((x.water_temperature, x.seat_temperature, x.air_temperature), (4, 2, 3))
        self.assertEqual((x.wind_speed, x.wide_wash_level), (1, 3))
        self.assertFalse(x.smart_power_save)
        self.assertFalse(x.flushing)
        self.assertTrue(x.auto_small_flush)
        self.assertTrue(x.foot_sensor)
        self.assertEqual(x.foam_level, FoamLevel.LOW)
        self.assertTrue(decode_extended(f(FA_FLUSHING)).small_flushing)
        self.assertFalse(decode_extended(f(FA_OFF)).auto_cover)

    def test_e9(self):
        r = decode_runtime(f(E9_STANDBY))
        self.assertTrue(r.standby)
        self.assertFalse(r.seated)
        self.assertFalse(r.fault)
        self.assertFalse(r.water_shortage)
        for h in E9_FIXTURES:
            self.assertEqual(decode_runtime(f(h)).status, WorkStatus.STANDBY)

    def test_work_status_codes(self):
        self.assertEqual(work_status(3), WorkStatus.NOZZLE_CLEANING)
        self.assertEqual(work_status(0x83), WorkStatus.NOZZLE_REPLACEMENT)
        self.assertEqual(work_status(0x90), WorkStatus.DRYING)
        self.assertEqual(work_status(0x20), WorkStatus.HIP_WASH)
        self.assertEqual(work_status(0x40), WorkStatus.LADY_WASH)
        self.assertEqual(work_status(0), WorkStatus.OTHER)

    def test_ea(self):
        closed = decode_mechanism(f(EA_CLOSED))
        self.assertEqual((closed.lid_open, closed.ring_open, closed.settled), (False, False, True))
        lid = decode_mechanism(f(EA_LID_OPEN))
        self.assertEqual((lid.lid_open, lid.ring_open), (True, False))
        both = decode_mechanism(f(EA_BOTH_OPEN))
        self.assertEqual((both.lid_open, both.ring_open), (True, True))
        moving = decode_mechanism(parse_frame(build_frame(0xEA, b"\x55" + bytes(12), 0x21, 0x22)))
        self.assertTrue(moving.lid_moving)
        self.assertFalse(moving.settled)
        transit = decode_mechanism(parse_frame(build_frame(0xEA, b"\xd0" + bytes(12), 0x21, 0x22)))
        self.assertIsNone(transit.lid_open)
        self.assertFalse(transit.settled)

    def test_e7(self):
        filt = decode_filter(f(E7))
        self.assertEqual(filt.used_minutes, 19 * 60 + 28)
        self.assertEqual(filt.remaining_percent, 91.6)


class EncodeTests(unittest.TestCase):
    def test_exact_vectors(self):
        settings = current()
        for op, h in VECTORS.items():
            with self.subTest(op=op):
                self.assertEqual(function_frame(op, settings).hex(), h)

    def test_auto_cover_vectors(self):
        off = with_changes(current(), {"auto_cover": False})
        self.assertEqual(function_frame(Op.APPLY_SETTINGS, off).hex(), AUTO_COVER_OFF)
        on = with_changes(current(E2_OFF, FA_OFF), {"auto_cover": True})
        self.assertEqual(function_frame(Op.APPLY_SETTINGS, on).hex(), AUTO_COVER_ON)

    def test_single_change_touches_only_its_bits(self):
        base = function_frame(Op.APPLY_SETTINGS, current())
        cases = {
            "water_temperature": (2, {6: 0x70}),
            "seat_temperature": (5, {7: 0x0F}),
            "air_temperature": (1, {8: 0x07}),
            "hip_pressure": (5, {8: 0x70}),
            "hip_nozzle": (2, {7: 0x70}),
            "wind_speed": (4, {11: 0xF0}),
            "wide_wash_level": (5, {9: 0xF0}),
            "auto_flush": (False, {6: 0x02}),
            "auto_night_light": (False, {8: 0x80}),
        }
        for name, (value, masks) in cases.items():
            with self.subTest(name=name):
                frame = function_frame(Op.APPLY_SETTINGS, with_changes(current(), {name: value}))
                for i in range(6, 17):
                    mask = masks.get(i, 0)
                    self.assertEqual(frame[i] & ~mask & 0xFF, base[i] & ~mask & 0xFF, i)
                self.assertNotEqual(frame, base)

    def test_read_only_and_ranges(self):
        for name in ("gesture", "night_light", "smart_power_save", "lady_pressure", "lady_nozzle"):
            with self.subTest(name=name), self.assertRaises(ProtocolError):
                with_changes(current(), {name: 1})
        for name, value in (
            ("water_temperature", 6),
            ("air_temperature", 5),
            ("hip_pressure", 0),
            ("wind_speed", 6),
            ("seat_temperature", -1),
            ("unknown", 1),
            ("auto_cover", 2),
        ):
            with self.subTest(name=name), self.assertRaises(ProtocolError):
                with_changes(current(), {name: value})
        with self.assertRaises(ProtocolError):
            function_frame(Op.STOP, current())
        with self.assertRaises(ProtocolError):
            function_frame(Op.CLOSE_LID, replace(current(), water_temperature=7))

    def test_e2_fa_disagreement_refused(self):
        with self.assertRaises(ProtocolError):
            writable_from(decode_settings(f(E2_ON)), decode_extended(f(FA_OFF)))

    def test_option_frames(self):
        self.assertEqual(
            option_frame(Option.UV_DISINFECTION, True).hex(), build_frame(0x1F, b"\x21\x40").hex()
        )
        self.assertEqual(option_frame(Option.UV_DISINFECTION, False)[6:8], b"\x21\x20")
        self.assertEqual(option_frame(Option.CLOSE_LID_BEFORE_FLUSH, True)[6:8], b"\x25\x01")
        self.assertEqual(option_frame(Option.AUTO_SMALL_FLUSH, False)[6:8], b"\x25\x08")
        self.assertEqual(option_frame(Option.FOOT_SENSOR, False)[6:8], b"\x24\x02")
        self.assertEqual(option_frame(Option.AMBIENT_LIGHT, True)[6:8], b"\x33\x20")
        self.assertEqual(len(option_frame(Option.AMBIENT_LIGHT, True)), 10)

    def test_settings_diff(self):
        before = (decode_settings(f(E2_ON)), decode_extended(f(FA_ON)))
        after = (decode_settings(f(E2_OFF)), decode_extended(f(FA_OFF)))
        self.assertEqual(settings_diff(before, after), {"auto_cover": (True, False)})
        self.assertEqual(settings_diff(before, after, frozenset({"auto_cover"})), {})


if __name__ == "__main__":
    unittest.main()
