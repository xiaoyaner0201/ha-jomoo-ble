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

    state = {"e2": E2, "fa": FA, "e9": E9, "ea": EA, "conns": 0, "writes": []}

    def with_byte(frame, i, v):
        p = proto.parse_frame(frame)
        pl = bytearray(p.payload)
        pl[i] = v
        return proto.build_frame(p.command, bytes(pl), p.source, p.destination)

    class FakeClient:
        is_connected = True

        async def start_notify(self, ch, cb):
            self.cb = cb

        async def write_gatt_char(self, ch, data, response):
            f = proto.parse_frame(bytes(data))
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
            self.is_connected = False

    def fake_make_session(hass_, address, prefix):
        async def connect():
            state["conns"] += 1
            return FakeClient()

        return client_mod.SessionManager(
            connect,
            response_timeout=1,
            action_timeout=2,
            flush_confirm_timeout=1,
            settle_time=0,
            poll_gap=0,
        )

    btmod.make_session = fake_make_session
    coord_mod = importlib.import_module("custom_components.jomoo_ble.coordinator")
    coord_mod.make_session = fake_make_session
    flow_mod = importlib.import_module("custom_components.jomoo_ble.config_flow")
    flow_mod.make_session = fake_make_session
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

    ents = [e for e in er.async_get(hass).entities.values() if e.config_entry_id == entry.entry_id]
    print("entities", len(ents), "disabled-by-default", sum(1 for e in ents if e.disabled_by))
    sw = next(e.entity_id for e in ents if e.unique_id.endswith("_auto_cover"))
    print("auto_cover state before refresh", hass.states.get(sw).state)

    # Refresh button -> state populated
    btn = next(e.entity_id for e in ents if e.unique_id.endswith("_refresh"))
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
    fb = next(e.entity_id for e in ents if e.unique_id.endswith("_small_flush"))
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

    # Unload
    ok = await hass.config_entries.async_unload(entry.entry_id)
    print("unload", ok, entry.state)
    print("total writes", len(state["writes"]), "total connections", state["conns"])
    await hass.async_stop(force=True)
    shutil.rmtree(cfg, ignore_errors=True)


asyncio.run(main())
