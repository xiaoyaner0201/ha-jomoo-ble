"""Tests use anonymized wire evidence, not a device or vendor package."""

import unittest

from jomoo_ble.protocol import (
    Action,
    FrameDecoder,
    ProtocolError,
    action_complete,
    build_frame,
    filter_query,
    mechanism,
    parameter_command,
    parse_frame,
    settings,
    state_query,
    validate_status,
)

E2_ON = "f3f40b2192e24a52b3450900003dfc"
E2_OFF = "f3f40b2192e24252b34509000035fc"
EA_CLOSED = "f3f4112122ea05008500804c13005f0000000006fc"


class ProtocolTests(unittest.TestCase):
    def test_queries_match_observed(self):
        self.assertEqual(state_query().hex(), "f3f4089200e2000000007cfc")
        self.assertEqual(filter_query().hex(), "f3f4089221e700000000a2fc")

    def test_real_frames_round_trip(self):
        for h in (
            E2_ON,
            E2_OFF,
            EA_CLOSED,
            "f3f40a2100e94500000100005afc",
            "f3f40c2100fa4a52b345113329335bfc",
            "f3f4082192e701c3131b94fc",
        ):
            with self.subTest(h=h):
                frame = parse_frame(bytes.fromhex(h))
                validate_status(frame)
                self.assertEqual(frame.encode().hex(), h)

    def test_every_checksum_bit_corruption_rejected(self):
        packet = bytes.fromhex(E2_ON)
        for position in range(2, len(packet) - 1):
            for bit in range(8):
                changed = bytearray(packet)
                changed[position] ^= 1 << bit
                with self.assertRaises(ProtocolError):
                    parse_frame(changed)

    def test_malformed_frames(self):
        valid = bytes.fromhex(E2_ON)
        for packet in (
            b"",
            b"\xf3\xf4",
            valid[:-1],
            valid + b"x",
            b"xx" + valid[2:],
            valid[:-1] + b"x",
            valid + valid,
        ):
            with self.assertRaises(ProtocolError):
                parse_frame(packet)
        with self.assertRaises(ProtocolError):
            build_frame(256, b"")
        with self.assertRaises(ProtocolError):
            build_frame(1, bytes(252))
        with self.assertRaises(ProtocolError):
            validate_status(parse_frame(build_frame(0xE2, b"x", source=0x21)))
        with self.assertRaises(ProtocolError):
            validate_status(parse_frame(state_query()))

    def test_stream_chunks_noise_corruption(self):
        first, second = bytes.fromhex(E2_ON), bytes.fromhex(EA_CLOSED)
        for split in range(len(first) + 1):
            decoder = FrameDecoder()
            found = decoder.feed(b"noise" + first[:split])
            found += decoder.feed(first[split:] + second)
            self.assertEqual([f.encode() for f in found], [first, second])
        decoder = FrameDecoder()
        bad = first[:-2] + b"\x00\xfc"
        self.assertEqual(decoder.feed(bad + first), [parse_frame(first)])
        decoder.feed(bytes(10000))
        self.assertLessEqual(len(decoder._buffer), 258)

    def test_verified_commands(self):
        state = parse_frame(bytes.fromhex(E2_ON))
        commands = {
            Action.OPEN_LID: "f3f40f9221114a52b3300010000000000062fc",
            Action.CLOSE_LID: "f3f40f9221104a52b3300010000000000061fc",
            Action.OPEN_RING: "f3f40f9221134a52b3300010000000000064fc",
            Action.CLOSE_RING: "f3f40f9221114a52b3300010000000000062fc",
            Action.SMALL_FLUSH: "f3f40f92210f4a52b3300010000000000060fc",
            Action.AUTO_COVER_OFF: "f3f40f9221194252b3300010000000000062fc",
            Action.AUTO_COVER_ON: "f3f40f9221194a52b330001000000000006afc",
        }
        for action, expected in commands.items():
            with self.subTest(action=action):
                actual = parameter_command(action, state)
                self.assertEqual(actual.hex(), expected)
                self.assertEqual(len(actual), 19)
                parse_frame(actual)

    def test_auto_cover_changes_no_other_parameter(self):
        for h in (E2_ON, E2_OFF):
            state = parse_frame(bytes.fromhex(h))
            before = settings(state)
            off = parameter_command(Action.AUTO_COVER_OFF, state)
            on = parameter_command(Action.AUTO_COVER_ON, state)
            self.assertEqual(off[7:-2], on[7:-2])
            self.assertEqual(off[6] ^ on[6], 0x08)
            self.assertEqual(off[:6], on[:6])
            self.assertEqual(on[-2] - off[-2], 8)
            # Known water/seat/air/pressure/nozzle/auto-flush values are retained.
            for other in (E2_ON, E2_OFF):
                observed = settings(parse_frame(bytes.fromhex(other)))
                self.assertEqual(
                    {k: v for k, v in before.items() if k != "auto_cover"},
                    {k: v for k, v in observed.items() if k != "auto_cover"},
                )

    def test_unknown_settings_refuse_all_writes(self):
        state = parse_frame(bytes.fromhex(E2_ON))
        for index in range(len(state.payload)):
            for bit in range(8):
                if index == 0 and bit == 3:
                    continue  # The independently verified automatic-cover bit.
                payload = bytearray(state.payload)
                payload[index] ^= 1 << bit
                changed = parse_frame(build_frame(0xE2, payload, source=0x21, destination=0x92))
                for action in Action:
                    with self.assertRaises(ProtocolError):
                        parameter_command(action, changed)
        with self.assertRaises(ProtocolError):
            parameter_command("factory_reset", state)

    def test_ea_decodes_independently_of_e2(self):
        base = parse_frame(bytes.fromhex(EA_CLOSED))
        # Physically observed: 05 closed, 19/09 lid open, 1A both open,
        # 55/49 lid moving, 75 both moving, 2A ring moving.
        cases = [
            (0x05, False, False, False, False),
            (0x19, True, False, False, False),
            (0x1A, True, True, False, False),
            (0x55, False, False, True, False),
            (0x49, True, False, True, False),
            (0x75, False, False, True, True),
            (0x2A, True, True, False, True),
        ]
        for flags, lid, ring, lid_run, ring_run in cases:
            frame = parse_frame(
                build_frame(0xEA, bytes([flags]) + base.payload[1:], source=0x21, destination=0x22)
            )
            got = mechanism(frame)
            self.assertEqual(
                (got.lid_open, got.ring_open, got.lid_moving, got.ring_moving),
                (lid, ring, lid_run, ring_run),
            )
        frame = parse_frame(build_frame(0xEA, bytes(13), source=0x21, destination=0x22))
        self.assertIsNone(mechanism(frame).lid_open)

    def test_completion_needs_observed_state(self):
        on = parse_frame(bytes.fromhex(E2_ON))
        off = parse_frame(bytes.fromhex(E2_OFF))
        self.assertFalse(action_complete(Action.AUTO_COVER_OFF, {0xE2: on}))
        self.assertTrue(action_complete(Action.AUTO_COVER_OFF, {0xE2: off}))
        self.assertFalse(action_complete(Action.CLOSE_LID, {}))
        self.assertTrue(
            action_complete(Action.CLOSE_LID, {0xEA: parse_frame(bytes.fromhex(EA_CLOSED))})
        )


if __name__ == "__main__":
    unittest.main()
