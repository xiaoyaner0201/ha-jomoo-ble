# ha-jomoo-ble

[简体中文](README.zh-CN.md) · Apache-2.0 · Unofficial Home Assistant custom integration

Local Bluetooth control of the **JOMOO ZS800J** smart toilet from Home Assistant, through
any connectable HA Bluetooth adapter or an ESPHome Bluetooth proxy placed near the toilet.
No cloud, no account, no vendor code.

## ⚠️ Breaking changes in 0.4.0

**Upgrade action is required if you used shower guard.** Removed:
`jomoo_ble.suspend_auto_cover` / `jomoo_ble.resume_auto_cover`, the automatic lid
switch's `guard_active`, `guard_pending`, `guard_previous` attributes, and the
*Shower guard active* binary sensor. The old blueprint and any automation referencing
these services, sensor or attributes are affected.

A device integration exposes device capabilities: entities, device actions and the
device page. Cross-device policy — when hot water flows, pause settings and restore
them later — belongs in Home Assistant automations, scripts and blueprints, not in
the device integration. The replacement uses HA's own scene snapshot/restore.

### Migrate from 0.3.x or earlier

1. Before upgrading, stop the old automation and check/restore Automatic lid opening
   if a pause is in progress. Updating never restores or writes a device setting.
2. Update the integration and restart HA. Obsolete policy storage and the old sensor's
   registry entry are removed best effort. An active/pending old pause logs one warning
   to check Automatic lid opening; its previous value is not migrated into a scene.
3. Re-import/update the blueprint at the same path and edit or recreate its automation:
   replace the old `toilet` input with `switches`, selecting **Automatic lid opening**
   and **Foot sensor**. Enable verified controls; experimental controls are not needed.
   Use the default **10-minute** delay and a unique reserved `scene_id` per automation.
4. Delete/replace automations calling either removed service. Remove any old fallback
   automation referencing `guard_active` / `guard_pending` or the removed sensor;
   recovery while a snapshot exists is now built into the blueprint.
5. Verify a complete on → off → restore cycle, including a switch that was originally
   off. Existing Foot sensor entity IDs remain unchanged (even if their IDs include
   “experimental”); only the display name changes. The old integration-disabled default
   is re-enabled, but a user-disabled entity stays disabled.

The minimal HA-native pattern is below (replace the example entity IDs). Call pause
when hot water starts and restore after it has been off for the delay. The blueprint
adds per-switch error isolation and bounded pause attempts to this basic example.

```yaml
script:
  toilet_pause:
    sequence:
      - condition: template
        value_template: "{{ states.scene.jomoo_shower_guard_before is none }}"
      - action: scene.create
        data:
          scene_id: jomoo_shower_guard_before
          snapshot_entities:
            - switch.toilet_auto_cover
            - switch.toilet_foot_sensor
      - action: switch.turn_off
        target:
          entity_id:
            - switch.toilet_auto_cover
            - switch.toilet_foot_sensor
  toilet_restore:
    sequence:
      - condition: template
        value_template: "{{ states.scene.jomoo_shower_guard_before is not none }}"
      - action: scene.turn_on
        target:
          entity_id: scene.jomoo_shower_guard_before
      - action: scene.delete
        target:
          entity_id: scene.jomoo_shower_guard_before
```

**Scenes created with `scene.create` do not survive an HA restart or scene reload.**
An interrupted pause cannot restore automatically after restart. Use one persistent
`input_boolean` per switch in your own automation if restart-proof memory is required,
or check the switches manually. Manual changes during a pause no longer cancel the
snapshot: the saved states will be restored. Restore is best effort; inspect traces
and settings after errors. See [HA-native shower guard](#shower-guard-ha-native).

## Why this exists

Automatic lid opening can be inconvenient near a shower: movement or steam can open
the lid while hot water is running. Home Assistant can pause both automatic lid
opening and the foot sensor, then restore exactly their previous states — a setting
that was already off stays off. This integration provides the device capabilities;
the [HA-native blueprint](blueprints/automation/jomoo_ble/shower_guard.yaml) provides
an optional, user-configured policy.

The protocol implementation is independent, based on wire observations, read-only
queries and read-back against the official controller's behaviour. No vendor source
or mini-program files are included or needed. Hardware checks cover lid/ring actions,
small flush, automatic lid opening and foot sensor off/on, with other settings unchanged.

## What you get

- **Status on demand**: lid / seat ring position and motion, seated, flushing, work status,
  water shortage, abnormal flow, sensor / overheat faults, filter remaining and hours,
  foam liquid low, every settings level, and a last-refresh timestamp.
- **Verified controls**: open / close lid, open / close seat ring, small flush, and the
  automatic lid opening and foot sensor switches.
- **HA-native shower guard blueprint**: snapshots one or more switches, pauses them
  during hot-water use and restores their original values afterwards. Configured in HA,
  not a service or policy inside this integration.
- **Experimental controls** (off by default): water / seat / dryer temperature levels,
  rear wash pressure and nozzle position, dryer fan speed, wide-wash level, automatic
  flush, automatic night light, UV water disinfection, close lid before flush, automatic
  small flush, ambient light, large flush.

## Hardware

- A JOMOO ZS800J (advertises as `JOMOO_SMART_237369`). Other models are refused.
- A connectable Bluetooth path from Home Assistant to the toilet: a local adapter, or an
  [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy/) with
  `active: true`. Bathrooms attenuate Bluetooth heavily; put the proxy close to the
  toilet (in testing, -90 dBm through a wall was unusable, -68 dBm beside it connected
  in under a second). Mind water and mains safety.
- With an ESPHome proxy, also set **Bluetooth scanning mode** to **Active** in the
  ESPHome device's integration options in Home Assistant. Recent HA versions default to
  *Auto*, which scans passively most of the time, so the toilet's name (sent only in
  scan responses) never reaches HA. The integration then refuses the device as an
  unsupported model and every entity becomes unavailable after a reload. `active: true`
  in the ESPHome YAML does not override this HA-side setting.

## Two things to know first

1. **Every connection makes the toilet beep.** The integration therefore never polls by
   default. By default, it connects only when you press *Refresh status*, call
   `jomoo_ble.refresh`, or run a command, and disconnects immediately. You can opt in to
   slow polling (300 s – 24 h) or persistent live status in the options.
2. **Only one Bluetooth central at a time.** While Home Assistant is connected, the
   official mini program cannot connect, and vice versa. With live status enabled, HA
   holds that connection continuously. Close the mini program before setup.

## Install

**HACS (custom repository)**: HACS → Integrations → ⋮ → Custom repositories → add
`https://github.com/xiaoyaner0201/ha-jomoo-ble` as *Integration*, install, restart.

**Manual**: copy `custom_components/jomoo_ble` (including `lib/`) into your HA
`config/custom_components/`, restart.

Then *Settings → Devices & services*: the toilet is usually discovered automatically;
otherwise *Add integration → JOMOO BLE* and enter its Bluetooth MAC (the field is
pre-filled when a matching advertisement is visible). `02:00:00:00:00:01` is a fictional
example. Setup performs one read-only query (one beep).

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| Enable verified controls | off | Lid, seat ring, small flush, automatic lid opening, foot sensor |
| Enable experimental controls | off | Everything marked *Experimental* below |
| Automatic refresh interval | 0 (off) | 0, or 300 – 86400 seconds |
| Persistent live status (`enable_status_stream`) | off | Hold one shared BLE connection; ignore polling while enabled |

### Opt-in live status (hardware-accepted, off by default)

Live status remains off by default and must be explicitly enabled in the integration
options. Enable it only if you accept continuous single-central
ownership: the initial connection beeps and the official app cannot connect until HA
releases Bluetooth. Initial validated E2/EA/E9/FA/E7 queries seed the snapshot; passive
notifications then update existing entities, including Flushing. This is not a refill
sensor: FA payload[5] bit0 is still unknown.

Stream, refresh and commands share the same physical connection and
operation lock. Controls still require a new full query window, preserve other settings,
write once and verify by read-back; stream caches never supply control settings.
No periodic query/reconnect or automatic recovery is scheduled. After loss, state is
unavailable; press the existing Refresh status button (or call `jomoo_ble.refresh`) for
one coalesced recovery attempt. Underlying bounded establish retries are unchanged.
Disabling the option, unloading, or stopping HA releases the connection; uncertain
release blocks control and is not reported as success.

Only when opted in, Live status connection and Last status received diagnostic entities
are added. Receive timestamps advance only on valid packets, with per-frame timestamps;
Last refresh still means an explicit complete query. Silence is not a new measurement,
and a connected backend without heartbeats is not proof that every field is current.
See [acquisition semantics and verification boundaries](docs/status-stream.md).
Hardware acceptance used HA 2026.9.1 through an ESPHome Bluetooth proxy: flush start
and end reached HA in real time through passive notifications, without periodic queries.
All 5 end-to-end hardware scenarios passed, including stream re-establishment after an
HA restart during an automation pause. After the final installation, one connection
stayed up for about 10.5 hours with no disconnects; all 9 daily flushes delivered
`flushing` on → off, and entities such as Flushing and Seated never became unavailable.
A separately maintained HA-native refill automation (not included in this repository)
acted about 0.5 seconds after flushing ended. This is not refill-complete detection or
a long-term stability guarantee; long-term observation continues.

If unloading fails, manually check Bluetooth release and restart HA: HA 2026.9.1 marks
the entry FAILED_UNLOAD and refuses a reload. Do not assume the phone can reconnect
until release is confirmed.

## Entities

| Entity | Type | Status |
| --- | --- | --- |
| Refresh status | button | Verified (read-only) |
| Open lid / Close lid / Open seat ring / Close seat ring | button | Verified |
| Small flush | button | Verified |
| Large flush | button | Experimental, disabled by default |
| Automatic lid opening, Foot sensor | switch | Verified, enabled in registry by default; config switches gated by verified controls |
| Automatic flush, automatic night light | switch | Experimental, disabled by default |
| UV water disinfection, close lid before flush, automatic small flush, ambient light | switch | Experimental, disabled by default |
| Water / seat / dryer temperature level, rear wash pressure, rear nozzle position, dryer fan speed, wide-wash level | number | Experimental, disabled by default (device levels, not °C) |
| Lid, Seat ring, Lid moving, Seat ring moving, Seated, Flushing | binary sensor | Read-only |
| Water shortage, Abnormal water flow, Sensor or overheat fault, Filter needs replacement, Foam liquid low | binary sensor | Read-only |
| Status, Filter remaining (%), Filter used (h), Front wash pressure / nozzle, Last refresh | sensor | Read-only |
| Raw E2 / FA / E9 / EA / E7 | sensor | Diagnostic, disabled by default |

*Verified* means the command was sent to a real ZS800J and the result was confirmed by
reading the device back, with every other setting unchanged. *Experimental* encodings
follow the same frame layout but have not yet been exercised on hardware; they still
read back and refuse to report success unless the device confirms it.

The ring and lid are linked on this model: opening the ring also opens the lid; closing
the ring leaves the lid open. The automatic lid opening sensor reacts to a person
standing in front of the toilet, so a lid you just closed may reopen if someone is there.

## Shower guard (HA-native)

Import/update the v0.4.0+ blueprint (same import path):

[![Open your Home Assistant instance and show the blueprint import dialog.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fxiaoyaner0201%2Fha-jomoo-ble%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fjomoo_ble%2Fshower_guard.yaml)

Inputs: a **hot-water-flowing** binary sensor, a `switches` list (select **Automatic lid
opening** and **Foot sensor**), `off_delay` (default **10 minutes**) and a unique reserved
`scene_id` (default `jomoo_shower_guard_before`, no `scene.` prefix). Enable verified
controls. Switches must be known on/off before the first snapshot. Do not reuse a scene
ID or change inputs during a pause.

Hot water on → `scene.create` with `snapshot_entities` once → turn off switches that
are on. A re-trigger never overwrites the original snapshot. Each switch has separate
error handling; the automation attempts to reach all-off up to 5 times, 30 s apart,
stopping early when hot water stops. These are HA automation attempts, not transport
write retries. Hot water off for the delay → `scene.turn_on` → `scene.delete` (confirmed
available in HA 2026.9.1), restoring both on and off values.

Use a signal that means hot water is in use, not just that the heater is powered, and
check that it really changes during a shower: look at its history and make sure the
automation's *last triggered* is set before relying on it.

### Tested A.O. Smith signal (corrected)

A China-market A.O. Smith gas water heater was tested through the community
[Ai-Link A.O. Smith](https://github.com/mopocv/Ai-Link_A.O.Smith) integration
(v1.4.0 or newer, which renews its short-lived app token by itself).

An earlier version of this README recommended its *burner heating* (`heating`) sensor.
That was wrong for this unit: the sensor stayed "not heating" for days, including during
a real shower with the fan at about 3000 rpm and 44% burner duty, so the guard never
triggered. The flow-rate reading is not reliable either: it was once non-zero with no
tap open.

The verified signal is **zero-cold-water (recirculation) switch on, or fan
speed above 0**. It also fires on recirculation and other hot-water use, which also
pauses the selected switches for a while. Replace the placeholder entity ids with your own.
When both sources are unavailable, the template keeps its previous state instead of
reading missing data as "hot water off":

```yaml
template:
  - binary_sensor:
      - name: Hot water in use
        unique_id: hot_water_in_use
        state: >-
          {% set recirculation = states('switch.water_heater_recirculation') %}
          {% set fan = states('sensor.water_heater_fan_speed') %}
          {% if recirculation in ['unknown', 'unavailable'] and not is_number(fan) %}
            {{ this.state == 'on' }}
          {% else %}
            {{ recirculation == 'on' or (fan | float(0)) > 0 }}
          {% endif %}
```

The blueprint defaults to a **10-minute** restore delay, so settings stay paused while
hot-water use winds down. Cloud data can pause for several minutes.

### Recovery and restart limitation

HA drops running `for:` timers on restart or automation reload. The blueprint checks
at HA start and every 5 minutes: if hot water has been off for the full delay **and the
snapshot scene still exists**, restore and delete it. An automation-only reload can
therefore recover while the dynamic scene remains. The recovery branch is not a new
snapshot and never guesses an old value.

**Dynamic scenes do not survive an HA restart or a scene reload.** A start trigger
cannot recover a lost snapshot. Check Automatic lid opening and Foot sensor after an
interrupted pause, or use one persistent `input_boolean` per switch in your own
restart-proof automation. Unlike the removed integration policy, manual changes do not
cancel snapshot restoration. Restore is best effort, not transactional: after a write
failure inspect automation traces and device settings. This blueprint has been tested
with a fake toilet in real HA; no new complete hardware shower cycle is claimed.

## Safety model

- Before any write, the integration reads E2, FA, E9 and EA in the same connection and
  refuses unless the toilet is in standby. Lid, ring and flush commands are also refused
  while someone is seated or while the lid or ring is moving.
- Function frames carry the full settings block; short option frames target one
  setting. Both use fresh reads and preserve unrelated settings. After the write,
  the integration reads back until the target is confirmed. It then compares every other known setting and raises with a
  before/after diff if anything else moved.
- Flush commands report "sent, unconfirmed" (logged warning) if the flushing flag is not
  seen within about 6 seconds.
- The integration **never retries a control write automatically**: a failed write may
  still have reached the toilet. No optimistic state is published.
- If a disconnect cannot be confirmed, the integration stops connecting. A failed unload
  requires manual Bluetooth-release checks and an HA restart; reload is not a guarantee.
- Washing, drying, nozzle cleaning, firmware update and factory reset are not
  implemented.

This is not a safety system. Do not rely on it for occupancy detection or mechanical
protection.

## Limitations

- Only the ZS800J protocol profile is implemented and only one unit has been tested.
- There is no transaction id in the protocol. A very late notification could be mistaken
  for a fresh answer.
- Experimental controls are app-derived and unverified on hardware.

## Development

To repeat the isolated HA lifecycle checks, run the official 2026.9.1 image with
`--network none --memory 2g --cpus 2 --rm`, mount this checkout read-only at `/repo`,
and execute `python3 /repo/tests/ha_smoke/smoke_in_ha_container.py /repo`.
Repeat with `--uncertainty` after `/repo` to test conservative failed-unload behavior,
then with `--handoff` to exercise transport loss before connection adoption through
real HA adapter, coordinator and entities (including release and manual recovery).
Do not mount a production config or Bluetooth hardware.

```sh
python -m unittest discover -s tests -v   # protocol + synthetic BLE / stream
python scripts/sync_library.py --check    # bundled lib/ identical to jomoo_ble/
python scripts/check_repository.py        # compile, links, no real MAC / private IP
ruff check . && ruff format --check .
```

`tests/ha_smoke/smoke_in_ha_container.py` runs the whole integration (config flow,
entities, services, migration, HA-native blueprint, options, diagnostics, unload) inside
a real Home Assistant Python environment against a fake toilet. Never point it at a production
config directory. Protocol details: [docs/protocol.md](docs/protocol.md). Verification
record: [docs/verification.md](docs/verification.md).

## Disclaimer

Unofficial and not affiliated with or endorsed by JOMOO. JOMOO and Home Assistant are
trademarks of their respective owners. The implementation is original. No vendor code,
mini-program package or asset is included or needed. Use at your own risk.

## License

[Apache-2.0](LICENSE)
