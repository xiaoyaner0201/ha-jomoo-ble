"""Opt-in stream business tests; fake only the physical BLE client."""

import asyncio
import unittest

from jomoo_ble.client import SessionError, SetSettings
from jomoo_ble.protocol import build_frame, parse_frame
from test_client import Device, E2, FA, FakeClient, manager, with_byte


class StreamTests(unittest.IsolatedAsyncioTestCase):
    def make(self, device=None):
        device = device or Device()
        session = manager(device)
        clients = []
        original = session._connect

        async def connect():
            client = await original()
            clients.append(client)
            return client

        session._connect = connect
        updates = []
        session.enable_stream(lambda: updates.append(session.stream_snapshot))
        return session, device, clients, updates

    async def test_opt_in_is_lazy_and_one_full_query(self):
        s, d, clients, updates = self.make()
        self.assertEqual(d.connections, 0)
        snap = await s.poll()
        self.assertEqual(d.connections, 1)
        self.assertTrue(s.stream_connected)
        self.assertEqual(snap.settings.water_temperature, 4)
        self.assertEqual(snap.filter.remaining_percent, 91.6)
        self.assertTrue(updates)
        self.assertEqual(d.writes, [])
        await s.close()
        self.assertFalse(clients[0].is_connected)

    async def test_passive_off_on_off_and_freshness(self):
        s, d, clients, _ = self.make()
        await s.poll()
        initial = s.stream_snapshot
        for value, expected in ((0x11, False), (0x15, True), (0x11, False)):
            clients[0].callback(None, bytearray(with_byte(FA, 4, value)))
            self.assertEqual(s.stream_snapshot.extended.flushing, expected)
            self.assertEqual(s.stream_snapshot.frames[0xE2], initial.frames[0xE2])
            self.assertEqual(s.stream_snapshot.received_at[0xE2], initial.received_at[0xE2])
        last = s.stream_snapshot
        await asyncio.sleep(0.01)
        self.assertIs(last, s.stream_snapshot)
        self.assertEqual(d.connections, 1)
        await s.close()

    async def test_invalid_fragmented_and_coalesced_frames(self):
        s, _, clients, _ = self.make()
        await s.poll()
        old = s.stream_snapshot
        cb = clients[0].callback
        for packet in (
            build_frame(0xFA, b"\x00"),
            build_frame(0xFA, parse_frame(FA).payload, 0x92),
            build_frame(0x99, b"\x00"),
            FA[:-2] + b"\x00\xfc",
        ):
            cb(None, bytearray(packet))
        self.assertIs(old, s.stream_snapshot)
        packet = with_byte(FA, 4, 0x15)
        cb(None, bytearray(packet[:6]))
        self.assertIs(old, s.stream_snapshot)
        cb(None, bytearray(packet[6:] + with_byte(FA, 5, 0x33)))
        self.assertTrue(s.stream_snapshot.extended.flushing is False)
        self.assertFalse(hasattr(s.stream_snapshot.extended, "refill"))
        await s.close()

    async def test_disconnect_no_reconnect_command_refused_manual_coalesced(self):
        s, d, clients, _ = self.make()
        await s.poll()
        clients[0].is_connected = False
        d.active -= 1
        s.connection_lost(clients[0])
        self.assertFalse(s.stream_connected)
        self.assertIsNone(s.stream_snapshot)
        await asyncio.sleep(0.01)
        self.assertEqual(d.connections, 1)
        with self.assertRaises(SessionError):
            await s.command(SetSettings({"auto_cover": False}))
        await asyncio.gather(*(s.poll() for _ in range(8)))
        self.assertEqual(d.connections, 2)
        await s.close()

    async def test_command_refresh_stream_one_client_fresh_single_write(self):
        s, d, _, _ = self.make()
        await s.poll()
        # The cached settings say 4, the next fresh read says 3.
        d.e2 = with_byte(E2, 0, 0x3A)
        d.fa = with_byte(FA, 0, 0x3A)
        await asyncio.gather(s.command(SetSettings({"auto_cover": False})), s.poll(), s.poll())
        self.assertEqual(d.connections, 1)
        self.assertEqual(d.max_active, 1)
        self.assertEqual(len(d.writes), 1)
        self.assertEqual(parse_frame(d.writes[0]).payload[0], 0x32)
        await s.close()
        self.assertEqual(d.active, 0)
        self.assertFalse(s._lock.locked())

    async def test_failed_initial_snapshot_never_live_or_retries_connections(self):
        s, d, _, updates = self.make()

        class Partial(FakeClient):
            async def write_gatt_char(self, characteristic, data, response):
                self.callback(None, bytearray(FA))

        async def connect():
            d.connections += 1
            d.active += 1
            return Partial(d)

        s._connect = connect
        with self.assertRaises(SessionError):
            await asyncio.gather(*(s.poll() for _ in range(4)))
        self.assertEqual(d.connections, 1)
        self.assertIsNone(s.stream_snapshot)
        self.assertFalse(s.stream_connected)
        self.assertTrue(all(u is None for u in updates))
        self.assertEqual(d.active, 0)
        await s.close()

    async def test_initial_requires_filter_and_partial_does_not_publish(self):
        s, d, _, updates = self.make()

        class NoFilter(FakeClient):
            async def write_gatt_char(self, characteristic, data, response):
                if parse_frame(bytes(data)).command != 0xE7:
                    await super().write_gatt_char(characteristic, data, response)

        async def connect():
            d.connections += 1
            d.active += 1
            return NoFilter(d)

        s._connect = connect
        with self.assertRaises(SessionError):
            await s.poll()
        self.assertFalse(s.stream_connected)
        self.assertTrue(all(u is None for u in updates))
        await s.close()

    async def test_uncertain_release_blocks_and_detaches_notifications(self):
        s, d, clients, _ = self.make(Device(stay_connected=True))
        await s.poll()
        with self.assertRaises(SessionError):
            await s.close()
        self.assertTrue(s.blocked)
        self.assertFalse(s.stream_connected)
        clients[0].callback(None, bytearray(FA))
        self.assertIsNone(s.stream_snapshot)

    async def test_close_drains_cancelled_shared_startup(self):
        s, d, _, _ = self.make()
        entered, finish = asyncio.Event(), asyncio.Event()
        original = s._connect

        async def delayed():
            entered.set()
            await finish.wait()
            return await original()

        s._connect = delayed
        waiter = asyncio.create_task(s.poll())
        await entered.wait()
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        closing = asyncio.create_task(s.close())
        await asyncio.sleep(0)
        finish.set()
        await asyncio.wait_for(closing, 1)
        self.assertEqual(d.active, 0)
        self.assertIsNone(s._changed)
        self.assertIsNone(s._window)
        self.assertIsNone(s._refresh_task)
        self.assertFalse(s._lock.locked())

    async def test_cancel_during_physical_establish_reclaims_late_socket(self):
        d = Device()
        s = manager(d)
        original = s._connect
        entered, finish = asyncio.Event(), asyncio.Event()

        async def delayed():
            entered.set()
            await finish.wait()
            return await original()

        s._connect = delayed
        task = asyncio.create_task(s.command(SetSettings({"auto_cover": False})))
        await entered.wait()
        task.cancel()
        finish.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(d.connections, 1)
        self.assertEqual(d.active, 0)
        self.assertEqual(d.writes, [])
        self.assertFalse(s._lock.locked())
        await s.close()

    async def test_cached_complete_state_cannot_satisfy_command_fresh_window(self):
        s, d, clients, _ = self.make()
        await s.poll()

        async def partial(characteristic, data, response):
            clients[0].callback(None, bytearray(FA))

        clients[0].write_gatt_char = partial
        with self.assertRaises(SessionError):
            await s.command(SetSettings({"auto_cover": False}))
        self.assertEqual(d.writes, [])
        self.assertEqual(d.connections, 1)
        self.assertFalse(s.stream_connected)
        await s.close()

    async def test_stream_still_checks_unrelated_settings_and_never_retries_write(self):
        s, d, _, _ = self.make(Device(corrupt_on_write=True))
        await s.poll()
        from jomoo_ble.client import VerificationError

        with self.assertRaises(VerificationError):
            await s.command(SetSettings({"auto_cover": False}))
        self.assertEqual(d.connections, 1)
        self.assertEqual(len(d.writes), 1)
        await s.close()

    async def test_disconnect_callback_latched_when_backend_property_lags(self):
        s, d, clients, _ = self.make()
        await s.poll()
        old = clients[0]
        s.connection_lost(old)  # is_connected is intentionally still True
        old.callback(None, bytearray(with_byte(FA, 4, 0x15)))
        self.assertIsNone(s.stream_snapshot)
        self.assertFalse(s.stream_connected)
        await s.poll()
        self.assertFalse(old.is_connected)
        self.assertEqual(d.connections, 2)
        self.assertEqual(d.max_active, 1)
        await s.close()

    async def test_failed_establish_is_coalesced_and_only_manual_retry_connects(self):
        s, d, _, _ = self.make()

        async def failing():
            d.connections += 1
            await asyncio.sleep(0)
            raise OSError("synthetic connection failure")

        s._connect = failing
        results = await asyncio.gather(*(s.poll() for _ in range(8)), return_exceptions=True)
        self.assertTrue(all(isinstance(r, OSError) for r in results))
        self.assertEqual(d.connections, 1)
        await asyncio.sleep(0.01)
        self.assertEqual(d.connections, 1)
        with self.assertRaises(OSError):
            await s.poll()
        self.assertEqual(d.connections, 2)
        await s.close()

    async def test_cancel_notify_registration_releases_socket(self):
        d = Device()
        s = manager(d)
        entered = asyncio.Event()

        class HangingNotify(FakeClient):
            async def start_notify(self, characteristic, callback):
                entered.set()
                await asyncio.Event().wait()

        async def connect():
            d.active += 1
            return HangingNotify(d)

        s._connect = connect
        task = asyncio.create_task(s.poll())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(d.active, 0)
        self.assertFalse(s._lock.locked())
        await s.close()

    async def test_cancel_after_single_write_releases_without_retry_or_optimism(self):
        s, d, clients, _ = self.make()
        await s.poll()
        physical = clients[0]
        original = physical.write_gatt_char
        entered = asyncio.Event()

        async def write(characteristic, data, response):
            if d.writes and parse_frame(bytes(data)).command == 0xE2:
                entered.set()
                await asyncio.Event().wait()
            await original(characteristic, data, response)

        physical.write_gatt_char = write
        task = asyncio.create_task(s.command(SetSettings({"auto_cover": False})))
        await entered.wait()
        self.assertTrue(s.stream_snapshot.settings.auto_cover)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(d.writes), 1)
        self.assertEqual(d.active, 0)
        self.assertFalse(s._lock.locked())
        self.assertIsNone(s.stream_snapshot)
        await s.close()

    async def test_cancel_command_releases_and_no_write_retry(self):
        s, d, clients, _ = self.make()
        await s.poll()
        entered = asyncio.Event()

        async def prepare(snapshot):
            entered.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(s.command(SetSettings({"auto_cover": False}), prepare))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(d.active, 0)
        self.assertFalse(s._lock.locked())
        self.assertFalse(s.stream_connected)
        self.assertEqual(d.writes, [])
        self.assertFalse(clients[0].is_connected)
        await s.close()
