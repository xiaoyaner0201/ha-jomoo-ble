"""Synthetic BLE transport tests, not Home Assistant or live-device tests."""

import asyncio
import unittest

from jomoo_ble.client import SessionError, SessionManager
from jomoo_ble.protocol import Action, ProtocolError, build_frame, parse_frame

E2 = bytes.fromhex("f3f40b2192e24a52b3450900003dfc")
EA = bytes.fromhex("f3f4112122ea05008500804c13005f0000000006fc")


class FakeClient:
    def __init__(self, factory):
        self.factory = factory
        self.callback = None
        self.writes = []
        self.is_connected = True
        self.state = factory.initial_state
        self.mechanism = factory.initial_mechanism
        self.acted = False

    async def start_notify(self, characteristic, callback):
        self.callback = callback

    async def write_gatt_char(self, characteristic, data, response):
        self.writes.append(bytes(data))
        await asyncio.sleep(0)
        frame = parse_frame(data)
        if frame.command == 0xE2:
            if self.factory.no_state:
                return
            self.callback(None, bytearray(self.state))
            if not (self.factory.missing_post_ea and self.acted):
                self.callback(None, bytearray(self.mechanism))
        elif frame.command != 0xE7:
            self.acted = True
            if self.factory.write_error:
                raise OSError("synthetic lost acknowledgement")
            if self.factory.ignore_action:
                return
            if frame.command == 0x19:
                self.state = build_frame(
                    0xE2,
                    bytes([frame.payload[0]]) + parse_frame(E2).payload[1:],
                    source=0x21,
                    destination=0x92,
                )
            elif frame.command == 0x11:
                self.mechanism = build_frame(
                    0xEA, b"\x09" + parse_frame(EA).payload[1:], source=0x21, destination=0x22
                )

    async def disconnect(self):
        self.factory.active -= 1
        if self.factory.disconnect_error:
            raise OSError("synthetic disconnect failure")
        self.is_connected = self.factory.silent_disconnect


class Factory:
    no_state = False
    write_error = False
    ignore_action = False
    disconnect_error = False
    missing_post_ea = False
    silent_disconnect = False
    initial_state = E2
    initial_mechanism = EA

    def __init__(self):
        self.clients = []
        self.active = 0
        self.max_active = 0

    async def connect(self):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        client = FakeClient(self)
        self.clients.append(client)
        return client

    def session(self):
        return SessionManager(
            self.connect, response_timeout=0.01, action_timeout=0.01, settle_time=0
        )


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_poll_queries_and_disconnects(self):
        factory = Factory()
        observed = await factory.session().poll()
        self.assertIn(0xE2, observed.frames)
        self.assertIn(0xEA, observed.frames)
        self.assertEqual([parse_frame(x).command for x in factory.clients[0].writes], [0xE2, 0xE7])
        self.assertFalse(factory.clients[0].is_connected)

    async def test_action_is_preceded_by_current_query_and_read_back(self):
        factory = Factory()
        snapshot = await factory.session().command(Action.AUTO_COVER_OFF)
        self.assertEqual(snapshot.frames[0xE2].payload[0], 0x42)
        self.assertEqual(
            [parse_frame(x).command for x in factory.clients[0].writes], [0xE2, 0xE7, 0x19, 0xE2]
        )

    async def test_no_state_no_action(self):
        factory = Factory()
        factory.no_state = True
        with self.assertRaises((SessionError, asyncio.TimeoutError)):
            await factory.session().command(Action.SMALL_FLUSH)
        self.assertEqual([parse_frame(x).command for x in factory.clients[0].writes], [0xE2, 0xE7])
        self.assertEqual(factory.active, 0)

    async def test_write_failure_not_retried_or_optimistic(self):
        factory = Factory()
        factory.write_error = True
        with self.assertRaises(OSError):
            await factory.session().command(Action.AUTO_COVER_OFF)
        self.assertEqual(sum(parse_frame(x).command == 0x19 for x in factory.clients[0].writes), 1)
        self.assertEqual(factory.active, 0)

    async def test_unconfirmed_action_fails(self):
        factory = Factory()
        factory.ignore_action = True
        with self.assertRaises(SessionError):
            await factory.session().command(Action.AUTO_COVER_OFF)
        self.assertEqual(sum(parse_frame(x).command == 0x19 for x in factory.clients[0].writes), 1)

    async def test_post_query_cannot_use_pre_action_ea(self):
        factory = Factory()
        factory.missing_post_ea = True
        with self.assertRaises((SessionError, asyncio.TimeoutError)):
            await factory.session().command(Action.OPEN_LID)
        self.assertEqual(factory.active, 0)

    async def test_concurrent_operations_use_one_connection(self):
        factory = Factory()
        session = factory.session()
        await asyncio.gather(session.poll(), session.command(Action.AUTO_COVER_OFF), session.poll())
        self.assertEqual(factory.max_active, 1)
        self.assertEqual(factory.active, 0)
        self.assertEqual(len(factory.clients), 3)

    async def test_disconnect_failure_blocks_new_connections(self):
        factory = Factory()
        factory.disconnect_error = True
        session = factory.session()
        with self.assertRaises(OSError):
            await session.poll()
        with self.assertRaises(SessionError):
            await session.poll()
        self.assertEqual(len(factory.clients), 1)

    async def test_shutdown_prevents_future_sessions(self):
        factory = Factory()
        session = factory.session()
        await session.close()
        with self.assertRaises(SessionError):
            await session.command(Action.SMALL_FLUSH)
        self.assertEqual(factory.clients, [])

    async def test_snapshot_is_immutable(self):
        snapshot = await Factory().session().poll()
        with self.assertRaises(TypeError):
            snapshot.frames[0xE2] = parse_frame(EA)

    async def test_unknown_profile_refuses_actuator_write(self):
        factory = Factory()
        factory.initial_state = build_frame(
            0xE2, bytes.fromhex("4a52b345080000"), source=0x21, destination=0x92
        )
        with self.assertRaises(ProtocolError):
            await factory.session().command(Action.SMALL_FLUSH)
        self.assertEqual([parse_frame(x).command for x in factory.clients[0].writes], [0xE2, 0xE7])
        self.assertEqual(factory.active, 0)

    async def test_motion_and_unknown_position_refuse_actuator_write(self):
        for flags in (0x55, 0x00):
            factory = Factory()
            factory.initial_mechanism = build_frame(
                0xEA, bytes([flags]) + parse_frame(EA).payload[1:], source=0x21, destination=0x22
            )
            with self.assertRaises(SessionError):
                await factory.session().command(Action.SMALL_FLUSH)
            self.assertEqual(
                [parse_frame(x).command for x in factory.clients[0].writes], [0xE2, 0xE7]
            )

    async def test_open_lid_does_not_close_already_open_ring(self):
        factory = Factory()
        factory.initial_mechanism = build_frame(
            0xEA, b"\x1a" + parse_frame(EA).payload[1:], source=0x21, destination=0x22
        )
        observed = await factory.session().command(Action.OPEN_LID)
        self.assertEqual(observed.frames[0xEA].payload[0], 0x1A)
        self.assertEqual([parse_frame(x).command for x in factory.clients[0].writes], [0xE2, 0xE7])

    async def test_silent_disconnect_failure_blocks_new_connections(self):
        factory = Factory()
        factory.silent_disconnect = True
        session = factory.session()
        with self.assertRaises(SessionError):
            await session.poll()
        with self.assertRaises(SessionError):
            await session.poll()
        self.assertEqual(len(factory.clients), 1)

    async def test_cancel_disconnects(self):
        factory = Factory()
        factory.no_state = True
        session = factory.session()
        task = asyncio.create_task(session.poll())
        while not factory.clients or not factory.clients[0].writes:
            await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(factory.active, 0)


if __name__ == "__main__":
    unittest.main()
