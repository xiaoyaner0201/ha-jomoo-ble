"""Exercise the published blueprint in real HA, using a template hot-water signal."""

import asyncio
from pathlib import Path
import shutil


async def async_test_blueprint(hass, root: Path, lid: str, foot: str, device: dict) -> None:
    from homeassistant.components.automation.config import (
        ValidationStatus,
        async_validate_config_item,
    )
    from homeassistant.setup import async_setup_component

    relative = "jomoo_ble/shower_guard.yaml"
    target = Path(hass.config.path("blueprints", "automation", relative))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / "blueprints" / "automation" / relative, target)
    assert await async_setup_component(hass, "scene", {"scene": []})
    assert all(hass.services.has_service("scene", s) for s in ("create", "turn_on", "delete"))
    print("scene.delete exists in HA 2026.9.1: registered by homeassistant.scene")
    assert await async_setup_component(
        hass, "input_boolean", {"input_boolean": {"smoke_hot_water": {"initial": False}}}
    )
    assert await async_setup_component(
        hass,
        "template",
        {
            "template": [
                {
                    "binary_sensor": [
                        {
                            "name": "Smoke hot water",
                            "unique_id": "smoke_hot_water",
                            "state": "{{ is_state('input_boolean.smoke_hot_water', 'on') }}",
                        }
                    ]
                }
            ]
        },
    )
    await hass.async_block_till_done()
    hot = "binary_sensor.smoke_hot_water"
    snapshot = "scene.jomoo_smoke_before"
    assert hass.states.is_state(hot, "off")
    config = {
        "id": "jomoo_smoke_native",
        "alias": "JOMOO smoke native",
        "use_blueprint": {
            "path": relative,
            "input": {"hot_water": hot, "switches": [lid, foot]},
        },
    }
    # Validate the imported file with defaults, then the actual short-delay instance.
    validated = await async_validate_config_item(hass, "automation", config)
    assert validated.validation_status is ValidationStatus.OK
    config["use_blueprint"]["input"].update(
        {"off_delay": {"seconds": 0.1}, "scene_id": "jomoo_smoke_before"}
    )
    validated = await async_validate_config_item(hass, "automation", config)
    assert validated.validation_status is ValidationStatus.OK
    assert await async_setup_component(hass, "automation", {"automation": [config]})
    await hass.async_block_till_done()
    automation = "automation.jomoo_smoke_native"
    assert hass.states.is_state(automation, "on")
    print(
        "blueprint validation PASS: imported, default 10 min and short-delay automation config valid"
    )

    async def call(domain, service, entity_id, **data):
        await hass.services.async_call(
            domain, service, {"entity_id": entity_id, **data}, blocking=True
        )

    async def wait_for(predicate):
        async with asyncio.timeout(20):
            while not predicate():
                await asyncio.sleep(0.02)
        # Do not drain active automation tasks here: a pending retry wait must
        # remain live so the test can deliver hot-water off before its timeout.
        await asyncio.sleep(0)

    for originally_on in (True, False):
        await call("switch", "turn_on", lid)
        await call("switch", "turn_on" if originally_on else "turn_off", foot)
        await call("input_boolean", "turn_on", "input_boolean.smoke_hot_water")
        await wait_for(
            lambda: (
                hass.states.get(snapshot) is not None
                and all(hass.states.is_state(s, "off") for s in (lid, foot))
            )
        )
        # A re-trigger must not replace the original snapshot with the paused values.
        await call("automation", "trigger", automation, variables={"trigger": {"id": "start"}})
        assert hass.states.get(snapshot) is not None
        await call("input_boolean", "turn_off", "input_boolean.smoke_hot_water")
        await wait_for(lambda: hass.states.get(snapshot) is None)
        assert hass.states.is_state(lid, "on")
        assert hass.states.is_state(foot, "on" if originally_on else "off")
        print(
            f"blueprint scenario PASS: foot originally {'on' if originally_on else 'off'}, snapshot preserved, restored, scene deleted"
        )

    # One failed target must not block another; stopping hot water ends the wait early.
    await call("switch", "turn_on", foot)
    device["fail_lid_off"] = True
    before = len(device["writes"])
    await call("input_boolean", "turn_on", "input_boolean.smoke_hot_water")
    await wait_for(lambda: hass.states.is_state(foot, "off"))
    assert device["e2"][6] & 0x08  # failed target did not change the device setting
    assert len(device["writes"]) == before + 2  # failed lid + successful foot
    device["fail_lid_off"] = False
    # Recovery must finish before the 30 s retry wait could expire on its own.
    async with asyncio.timeout(10):
        await call("input_boolean", "turn_off", "input_boolean.smoke_hot_water")
        await wait_for(lambda: hass.states.get(snapshot) is None)
    assert all(hass.states.is_state(s, "on") for s in (lid, foot))
    print(
        "blueprint partial failure PASS: other switch paused, hot-water off interrupted retry wait"
    )

    # Drop a running off timer by disabling the automation, keeping the scene alive.
    await call("switch", "turn_on", foot)
    await call("input_boolean", "turn_on", "input_boolean.smoke_hot_water")
    await wait_for(lambda: all(hass.states.is_state(s, "off") for s in (lid, foot)))
    await call("automation", "turn_off", automation)
    await call("input_boolean", "turn_off", "input_boolean.smoke_hot_water")
    await asyncio.sleep(0.15)
    assert hass.states.get(snapshot) is not None
    await call("automation", "turn_on", automation)
    # Run the same action branch used by periodic/start recovery, without a 5-min wait.
    await call("automation", "trigger", automation, variables={"trigger": {"id": "recovery"}})
    await wait_for(lambda: hass.states.get(snapshot) is None)
    assert all(hass.states.is_state(s, "on") for s in (lid, foot))
    await call("automation", "turn_off", automation)
    print("blueprint recovery PASS: lost off timer restored while snapshot exists")

    # An unavailable switch at restore time must keep the snapshot: HA skips unavailable
    # entities without error, so restoring then would silently lose the original values.
    await call("automation", "turn_on", automation)
    await call("switch", "turn_on", foot)
    await call("input_boolean", "turn_on", "input_boolean.smoke_hot_water")
    await wait_for(lambda: all(hass.states.is_state(s, "off") for s in (lid, foot)))
    real_lid = hass.states.get(lid)
    hass.states.async_set(lid, "unavailable", real_lid.attributes)
    await call("input_boolean", "turn_off", "input_boolean.smoke_hot_water")
    await asyncio.sleep(0.3)
    await call("automation", "trigger", automation, variables={"trigger": {"id": "recovery"}})
    await asyncio.sleep(0.3)
    assert hass.states.get(snapshot) is not None, "snapshot dropped while a switch was unavailable"
    assert hass.states.is_state(foot, "off")
    hass.states.async_set(lid, real_lid.state, real_lid.attributes)
    await call("automation", "trigger", automation, variables={"trigger": {"id": "recovery"}})
    await wait_for(lambda: hass.states.get(snapshot) is None)
    assert all(hass.states.is_state(s, "on") for s in (lid, foot))
    await call("automation", "turn_off", automation)
    print("blueprint unavailable PASS: snapshot kept until switches return, then restored")
