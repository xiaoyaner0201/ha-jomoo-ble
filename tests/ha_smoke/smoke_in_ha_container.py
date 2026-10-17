"""Smoke test inside a real Home Assistant Python environment (e.g. the official container).

Usage (inside the container, never against a production config directory):
    python3 smoke_in_ha_container.py <dir containing custom_components/jomoo_ble>


Starts a throwaway HomeAssistant core in a temp config dir (no HTTP, no real bluetooth),
patches the BLE connector with a fake toilet, and exercises setup, entities, services,
shower guard, options and unload.
"""

import asyncio
import pathlib
import sys
import tempfile
import shutil
import importlib

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")

E2 = bytes.fromhex("f3f40b2192e24a52b3450900003dfc")
FA = bytes.fromhex("f3f40c2100fa4a52b345113229335afc")
E9 = bytes.fromhex("f3f40a2100e94500000100005afc")
EA = bytes.fromhex("f3f4112122ea05008500804c13005f0000000006fc")
E7 = bytes.fromhex("f3f4082192e701c3131c95fc")


async def main():
    from homeassistant import core, loader
    from homeassistant.const import __version__

    assert __version__ == "2026.9.1", __version__
    print("Home Assistant", __version__)
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.helpers import entity_registry as er, translation
    from homeassistant.setup import async_setup_component

    cfg = tempfile.mkdtemp(prefix="jomoo_cfg_")
    shutil.copytree(ROOT / "custom_components", pathlib.Path(cfg) / "custom_components")
    hass = core.HomeAssistant(cfg)
    hass.config.skip_pip = True
    from homeassistant import bootstrap, config_entries as ce

    hass.config_entries = ce.ConfigEntries(hass, {})
    loader.async_setup(hass)
    assert await bootstrap.async_load_base_functionality(hass)
    await hass.async_start()
    hass.data["custom_components"] = None  # force rescan
    integ = await loader.async_get_integration(hass, "jomoo_ble")
    print(
        "integration",
        integ.domain,
        integ.version,
        "bluetooth matcher",
        integ.manifest.get("bluetooth"),
    )

    sys.path.insert(0, cfg)
    proto = importlib.import_module("custom_components.jomoo_ble.lib.protocol")
    client_mod = importlib.import_module("custom_components.jomoo_ble.lib.client")
    btmod = importlib.import_module("custom_components.jomoo_ble.bluetooth")

    state = {
        "e2": E2,
        "fa": FA,
        "e9": E9,
        "ea": EA,
        "conns": 0,
        "writes": [],
        "queries": [],
        "connect_error": False,
    }

    def with_byte(frame, i, v):
        p = proto.parse_frame(frame)
        pl = bytearray(p.payload)
        pl[i] = v
        return proto.build_frame(p.command, bytes(pl), p.source, p.destination)

    clients = []

    class FakeClient:
        def __init__(self, disconnected_callback):
            self.is_connected = True
            self.disconnected_callback = disconnected_callback
            clients.append(self)
            assert sum(c.is_connected for c in clients) == 1

        async def start_notify(self, ch, cb):
            self.cb = cb

        async def write_gatt_char(self, ch, data, response):
            f = proto.parse_frame(bytes(data))
            if f.command in (0xE2, 0xE7):
                state["queries"].append(f.command)
            if f.command == 0xE2:
                for x in (state["e2"], state["ea"], state["e9"], state["fa"]):
                    self.cb(None, bytearray(x))
                return
            if f.command == 0xE7:
                self.cb(None, bytearray(E7))
                return
            state["writes"].append(bytes(data).hex())
            if f.command == 0x19:
                state["e2"] = with_byte(state["e2"], 0, f.payload[0])
                state["fa"] = with_byte(state["fa"], 0, f.payload[0])
            elif f.command == 0x11:
                state["ea"] = with_byte(state["ea"], 0, 0x09)
            elif f.command == 0x10:
                state["ea"] = with_byte(state["ea"], 0, 0x05)
            elif f.command == 0x0F:
                state["fa"] = with_byte(state["fa"], 4, 0x15)

        async def disconnect(self):
            if state.get("disconnect_uncertain"):
                return  # backend fails to release, while reporting success
            self.is_connected = False
            self.disconnected_callback(self)

    async def fake_establish(client_class, device, name, **kwargs):
        assert kwargs["max_attempts"] == 2
        state["conns"] += 1
        if state["connect_error"]:
            raise OSError("synthetic establish failure")
        return FakeClient(kwargs["disconnected_callback"])

    # Keep the real HA routing adapter and SessionManager; fake only radio discovery
    # and physical establishment. No real Bluetooth integration or adapter is started.
    from types import SimpleNamespace

    btmod.establish_connection = fake_establish
    btmod.bluetooth.async_last_service_info = lambda *a, **kw: SimpleNamespace(
        name="JOMOO_SMART_237369"
    )
    btmod.bluetooth.async_ble_device_from_address = lambda *a, **kw: object()
    coord_mod = importlib.import_module("custom_components.jomoo_ble.coordinator")
    flow_mod = importlib.import_module("custom_components.jomoo_ble.config_flow")
    flow_mod.async_discovered_service_info = lambda hass, connectable=True: []

    # translations / strings sanity through HA's own loader
    for lang in ("en", "zh-Hans"):
        t = await translation.async_get_translations(hass, lang, "entity", ["jomoo_ble"])
        print(lang, "entity translations", len(t))

    # Config flow (manual)
    await async_setup_component(hass, "homeassistant", {})
    hass.config.components.add("bluetooth")  # pretend dependency satisfied
    hass.config.components.add("bluetooth_adapters")
    result = await hass.config_entries.flow.async_init("jomoo_ble", context={"source": "user"})
    print("flow step", result["step_id"])
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"address": "zz", "name_prefix": "JOMOO_SMART_"}
    )
    print("bad mac errors", result.get("errors"))
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"address": "02:00:00:00:00:01", "name_prefix": "JOMOO_SMART_"}
    )
    print("flow result", result["type"], result.get("title"), "conns", state["conns"])
    entry = hass.config_entries.async_entries("jomoo_ble")[0]
    await hass.async_block_till_done()
    print("entry state", entry.state, "conns after setup (should be 1 = flow only)", state["conns"])
    assert state["conns"] == 1
    assert not entry.runtime_data.stream_enabled
    assert not any(c.is_connected for c in clients)

    ents = [e for e in er.async_get(hass).entities.values() if e.config_entry_id == entry.entry_id]
    assert not any(
        e.unique_id.endswith(("_status_stream_connected", "_last_status_received")) for e in ents
    )
    print("entities", len(ents), "disabled-by-default", sum(1 for e in ents if e.disabled_by))
    sw = next(e.entity_id for e in ents if e.unique_id.endswith("_auto_cover"))
    print("auto_cover state before refresh", hass.states.get(sw).state)

    # Refresh button -> state populated
    btn = next(
        e.entity_id for e in ents if e.domain == "button" and e.unique_id.endswith("_refresh")
    )
    await hass.services.async_call("button", "press", {"entity_id": btn}, blocking=True)
    print(
        "after refresh: auto_cover",
        hass.states.get(sw).state,
        "attrs",
        {k: v for k, v in hass.states.get(sw).attributes.items() if k.startswith("guard")},
    )
    for suffix in (
        "_lid_open",
        "_filter_remaining",
        "_work_status",
        "_seated",
        "_guard_active",
        "_last_refresh",
    ):
        eid = next(e.entity_id for e in ents if e.unique_id.endswith(suffix))
        print("  ", suffix, hass.states.get(eid).state)

    # Controls disabled -> service must fail
    try:
        await hass.services.async_call(
            "jomoo_ble", "suspend_auto_cover", {"entity_id": sw}, blocking=True
        )
        print("ERROR: suspend allowed while controls disabled", len(state["writes"]))
    except Exception as e:
        print("controls disabled ->", type(e).__name__, e)

    # Enable controls via options flow
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {"enable_controls": True, "enable_experimental": False, "poll_interval": 60}
    )
    print("bad interval errors", r.get("errors"))
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {"enable_controls": True, "enable_experimental": False, "poll_interval": 0}
    )
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries("jomoo_ble")[0]
    print("options", dict(entry.options), "state", entry.state)

    # Shower guard
    await hass.services.async_call(
        "jomoo_ble", "suspend_auto_cover", {"entity_id": sw}, blocking=True
    )
    a = hass.states.get(sw)
    print(
        "after suspend: auto_cover",
        a.state,
        {k: v for k, v in a.attributes.items() if k.startswith("guard")},
        "last write",
        state["writes"][-1],
    )
    await hass.services.async_call(
        "jomoo_ble", "resume_auto_cover", {"entity_id": sw}, blocking=True
    )
    a = hass.states.get(sw)
    print(
        "after resume: auto_cover",
        a.state,
        {k: v for k, v in a.attributes.items() if k.startswith("guard")},
        "last write",
        state["writes"][-1],
    )

    # Mechanical + flush
    ob = next(e.entity_id for e in ents if e.unique_id.endswith("_open_lid"))
    await hass.services.async_call("button", "press", {"entity_id": ob}, blocking=True)
    print(
        "lid after open",
        hass.states.get(next(e.entity_id for e in ents if e.unique_id.endswith("_lid_open"))).state,
    )
    fb = next(
        e.entity_id for e in ents if e.domain == "button" and e.unique_id.endswith("_small_flush")
    )
    await hass.services.async_call("button", "press", {"entity_id": fb}, blocking=True)
    print(
        "flushing",
        hass.states.get(next(e.entity_id for e in ents if e.unique_id.endswith("_flushing"))).state,
    )

    # Experimental refused
    num = next(e for e in ents if e.unique_id.endswith("_water_temperature"))
    print("experimental number disabled_by", num.disabled_by)

    # refresh service by device
    from homeassistant.helpers import device_registry as dr

    dev = next(iter(dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)))
    before = state["conns"]
    await hass.services.async_call("jomoo_ble", "refresh", {"device_id": [dev.id]}, blocking=True)
    print("refresh service conns +", state["conns"] - before)

    # diagnostics
    diag = importlib.import_module("custom_components.jomoo_ble.diagnostics")
    d = await diag.async_get_config_entry_diagnostics(hass, entry)
    print("diag address redacted:", d["entry"]["data"]["address"], "guard", d["guard"])

    # Opt-in stream lifecycle through real options reload, entities and services.
    old_ids = {e.unique_id: e.entity_id for e in ents}
    before = state["conns"]
    query_count = len(state["queries"])
    writes_before_stream = len(state["writes"])
    r = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        r["flow_id"],
        {
            "enable_controls": True,
            "enable_experimental": False,
            "poll_interval": 300,
            "enable_status_stream": True,
        },
    )
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    assert isinstance(coordinator, coord_mod.JomooCoordinator)
    assert isinstance(coordinator.session, client_mod.SessionManager)
    assert coordinator.update_interval is None  # stream never schedules polling
    assert state["conns"] == before + 1
    assert state["queries"][query_count:] == [0xE2, 0xE7]
    assert len(state["writes"]) == writes_before_stream
    assert coordinator.session.stream_connected
    ents = [e for e in er.async_get(hass).entities.values() if e.config_entry_id == entry.entry_id]
    assert all(old_ids.get(e.unique_id, e.entity_id) == e.entity_id for e in ents)
    assert not any("refill" in e.unique_id for e in ents)

    def eid(suffix):
        return next(e.entity_id for e in ents if e.unique_id.endswith(suffix))

    live = eid("_status_stream_connected")
    received = eid("_last_status_received")
    flushing = eid("_flushing")
    assert hass.states.get(live).state == "on"
    for value, expected in ((0x11, "off"), (0x15, "on"), (0x11, "off")):
        clients[-1].cb(None, bytearray(with_byte(FA, 4, value)))
        await hass.async_block_till_done()
        assert hass.states.get(flushing).state == expected
    timestamp = hass.states.get(received).state
    await asyncio.sleep(0.02)
    await hass.async_block_till_done()
    assert hass.states.get(received).state == timestamp
    assert state["queries"][query_count:] == [0xE2, 0xE7]
    assert "0xE2" in hass.states.get(received).attributes["frame_received_at"]
    physical = state["conns"]
    await asyncio.gather(
        coordinator.async_command(client_mod.SetSettings({"auto_cover": False})),
        coordinator.async_refresh_now(),
        coordinator.async_refresh_now(),
    )
    assert state["conns"] == physical
    await coordinator.async_command(client_mod.SetSettings({"auto_cover": True}))
    writes_before_guard = len(state["writes"])
    await hass.services.async_call(
        "jomoo_ble", "suspend_auto_cover", {"entity_id": sw}, blocking=True
    )
    assert entry.runtime_data.guard_state.previous is True
    assert entry.runtime_data.guard_state.active
    assert hass.states.get(sw).state == "off"
    await hass.services.async_call(
        "jomoo_ble", "resume_auto_cover", {"entity_id": sw}, blocking=True
    )
    assert len(state["writes"]) == writes_before_guard + 2
    assert hass.states.get(sw).state == "on"
    assert state["conns"] == physical
    assert not entry.runtime_data.guard_state.active

    # Physical loss immediately invalidates state. No timer or command reconnects.
    lost_client = clients[-1]
    await lost_client.disconnect()
    await hass.async_block_till_done()
    assert hass.states.get(live).state == "off"
    assert hass.states.get(flushing).state == "unavailable"
    assert hass.states.get(btn).state != "unavailable"
    assert not hass.states.get(received).attributes["live"]
    try:
        await coordinator.async_command(client_mod.SetSettings({"auto_cover": True}))
        raise AssertionError("control reconnected without manual permission")
    except HomeAssistantError:
        pass
    await asyncio.sleep(0.02)
    assert state["conns"] == physical
    await asyncio.gather(*(coordinator.async_refresh_now() for _ in range(6)))
    await hass.async_block_till_done()
    assert state["conns"] == physical + 1
    assert hass.states.get(live).state == "on"
    # A queued callback from the previous connection must not revive/alter state.
    snapshot = coordinator.data
    lost_client.cb(None, bytearray(with_byte(FA, 4, 0x15)))
    assert coordinator.data is snapshot

    # Disable via options: physical socket released and legacy IDs preserved.
    previous = clients[-1]
    r = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        r["flow_id"],
        {
            "enable_controls": True,
            "enable_experimental": False,
            "poll_interval": 0,
            "enable_status_stream": False,
        },
    )
    await hass.async_block_till_done()
    assert not previous.is_connected
    assert coordinator.session._changed is None
    assert coordinator.session._window is None
    assert not coordinator.session._lock.locked()
    assert not any(c.is_connected for c in clients)
    print(
        "stream lifecycle assertions PASS: startup, off/on/off, freshness, single client, guard, loss, manual recovery, option release, IDs"
    )

    # Failed opt-in startup remains loaded/off, never entering HA setup retry.
    before = state["conns"]
    state["connect_error"] = True
    r = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        r["flow_id"],
        {
            "enable_controls": True,
            "enable_experimental": False,
            "poll_interval": 0,
            "enable_status_stream": True,
        },
    )
    await hass.async_block_till_done()
    assert entry.state is ce.ConfigEntryState.LOADED
    assert state["conns"] == before + 1
    assert hass.states.get(live).state == "off"
    assert hass.states.get(flushing).state == "unavailable"
    assert entry.runtime_data.update_interval is None
    assert entry.runtime_data.data is None
    assert entry.runtime_data._unsub_refresh is None
    state["connect_error"] = False
    await hass.services.async_call("button", "press", {"entity_id": btn}, blocking=True)
    await hass.async_block_till_done()
    assert state["conns"] == before + 2
    assert clients[-1].is_connected

    # Unload
    ok = await hass.config_entries.async_unload(entry.entry_id)
    assert ok
    assert not any(c.is_connected for c in clients)
    print("unload", ok, entry.state)
    before = state["conns"]
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert state["conns"] == before + 1
    assert clients[-1].is_connected

    if "--uncertainty" in sys.argv:
        # HA marks failed unload non-recoverable: this must not free ownership or
        # permit another physical connection. Run separately from normal-stop test.
        coordinator = entry.runtime_data
        physical = state["conns"]
        state["disconnect_uncertain"] = True
        assert not await hass.config_entries.async_unload(entry.entry_id)
        assert entry.state is ce.ConfigEntryState.FAILED_UNLOAD
        assert coordinator.session.blocked
        assert clients[-1].is_connected
        assert hass.states.get(live).state == "off"
        assert hass.states.get(flushing).state == "unavailable"
        assert hass.states.get(live).attributes["disconnect_uncertain"]
        try:
            await hass.config_entries.async_reload(entry.entry_id)
            raise AssertionError("reload bypassed failed unload")
        except ce.OperationNotAllowed:
            pass
        assert state["conns"] == physical
        try:
            await coordinator.async_command(client_mod.SetSettings({"auto_cover": True}))
            raise AssertionError("uncertain disconnect allowed control")
        except HomeAssistantError:
            pass
        # Test-only physical recovery for cleanup; no integration reconnect/retry loop.
        state["disconnect_uncertain"] = False
        await coordinator.async_close()
        assert not any(c.is_connected for c in clients)
        print("uncertain release/FAILED_UNLOAD/reload/control blocking assertions PASS")

    await hass.async_stop(force=True)
    assert not any(c.is_connected for c in clients)
    assert entry.runtime_data.session._changed is None
    assert not entry.runtime_data.session._lock.locked()
    print(
        "failed startup/manual recovery/entry restart with retained options/HA stop assertions PASS"
    )
    print("total writes", len(state["writes"]), "total connections", state["conns"])
    shutil.rmtree(cfg, ignore_errors=True)


asyncio.run(main())
