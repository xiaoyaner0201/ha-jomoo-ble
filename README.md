# ha-jomoo-ble

[简体中文](README.zh-CN.md) · Apache-2.0 · Unofficial Home Assistant custom integration

Local Bluetooth control of the **JOMOO ZS800J** smart toilet from Home Assistant, through
any connectable HA Bluetooth adapter or an ESPHome Bluetooth proxy placed near the toilet.
No cloud, no account, no vendor code.

<!-- STORY:START -->
## Why this exists

Our toilet sits right next to the shower.

The JOMOO ZS800J has a handy *automatic lid opening* feature: walk up and the lid lifts by itself. During a shower, though, it misfires — someone standing nearby and drifting steam keep popping the lid open, right next to the running water.

So the first and final goal of this project fits in one sentence:

> **While the water heater is delivering hot water, turn the toilet's automatic lid opening off; when the hot water stops, put it back the way it was.**

"The way it was" matters: if automatic lid opening was already off before the shower, it stays off afterwards.

To get there, Home Assistant first had to really understand this toilet — hence this integration.
<!-- STORY:END -->

<!-- DEVLOG:START -->
## How it was built (short version)

1. **Reaching the device.** The toilet speaks Bluetooth only. An M5Stack CoreS3 running ESPHome serves as a Bluetooth proxy next to it: placed far away the signal was about -90 dBm and a connection took over ten seconds; beside the toilet it is about -68 dBm and connects in under a second.
2. **The official WeChat mini program as the reference.** JOMOO's official controller is a WeChat mini program. We used it as the reference: which protocol revision this model uses and what each status field means — then verified everything with our own **read-only queries and read-back**, field by field, against the mini program and the physical toilet. That turned "guessing a protocol" into "checking against a reference". This repository contains and needs **no vendor code or mini-program files**; the implementation is written independently.
3. **Step-by-step acceptance on the real device.** Read-only first, then reversible actions, then settings: open/close lid, open/close seat ring, small flush, automatic lid opening off/on — each verified on hardware. Every control frame carries the full settings block, so each write starts from a fresh read and is compared before/after to prove water/seat/dryer temperatures were not silently changed.
4. **An accidental proof.** During the close-lid test the lid reopened a few seconds later — someone was standing in front of the toilet watching, and automatic lid opening did exactly what it does. That is precisely the problem this project solves.
5. **Home Assistant.** Every connection makes the toilet beep, and only one central may connect at a time, so the integration does **not** poll by default; it connects briefly on refresh, on an action, or when an automation fires, and disconnects right away.
6. **Shower guard.** Two services — suspend / resume automatic lid opening — remember the previous state; a blueprint wires in any "hot water is flowing" sensor.
<!-- DEVLOG:END -->

## What you get

- **Status on demand**: lid / seat ring position and motion, seated, flushing, work status,
  water shortage, abnormal flow, sensor / overheat faults, filter remaining and hours,
  foam liquid low, every settings level, and a last-refresh timestamp.
- **Verified controls**: open / close lid, open / close seat ring, small flush, and the
  automatic lid opening switch.
- **Shower guard**: `jomoo_ble.suspend_auto_cover` / `jomoo_ble.resume_auto_cover`
  services plus an automation blueprint. While hot water is flowing, automatic lid
  opening is turned off; afterwards it is restored to exactly what it was.
- **Experimental controls** (off by default): water / seat / dryer temperature levels,
  rear wash pressure and nozzle position, dryer fan speed, wide-wash level, automatic
  flush, automatic night light, UV water disinfection, close lid before flush, automatic
  small flush, foot sensor, ambient light, large flush.

## Hardware

- A JOMOO ZS800J (advertises as `JOMOO_SMART_237369`). Other models are refused.
- A connectable Bluetooth path from Home Assistant to the toilet: a local adapter, or an
  [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy/) with
  `active: true`. Bathrooms attenuate Bluetooth heavily; put the proxy close to the
  toilet (in testing, -90 dBm through a wall was unusable, -68 dBm beside it connected
  in under a second). Mind water and mains safety.

## Two things to know first

1. **Every connection makes the toilet beep.** The integration therefore never polls by
   default. It connects only when you press *Refresh status*, call `jomoo_ble.refresh`,
   or run a command, and disconnects immediately. You can opt in to slow polling
   (300 s – 24 h) in the options.
2. **Only one Bluetooth central at a time.** While Home Assistant is connected (a few
   seconds), the official mini program cannot connect, and vice versa. Close the mini
   program before setup.

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
| Enable verified controls | off | Lid, seat ring, small flush, automatic lid opening, shower guard |
| Enable experimental controls | off | Everything marked *Experimental* below |
| Automatic refresh interval | 0 (off) | 0, or 300 – 86400 seconds |
| Persistent live status (`enable_status_stream`) | off | Hold one shared BLE connection; ignore polling while enabled |

### Opt-in live status (candidate, not hardware-accepted)

Enable this in the integration options only if you accept continuous single-central
ownership: the initial connection beeps and the official app cannot connect until HA
releases Bluetooth. Initial validated E2/EA/E9/FA/E7 queries seed the snapshot; passive
notifications then update existing entities, including Flushing. This is not a refill
sensor: FA payload[5] bit0 is still unknown.

Stream, refresh, commands and shower guard share the same physical connection and
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
The candidate has synthetic BLE / real-HA lifecycle coverage, not live HA/proxy acceptance.

## Entities

| Entity | Type | Status |
| --- | --- | --- |
| Refresh status | button | Verified (read-only) |
| Open lid / Close lid / Open seat ring / Close seat ring | button | Verified |
| Small flush | button | Verified |
| Large flush | button | Experimental, disabled by default |
| Automatic lid opening | switch | Verified; exposes `guard_active`, `guard_pending`, `guard_previous` |
| Automatic flush, automatic night light | switch | Experimental, disabled by default |
| UV water disinfection, close lid before flush, automatic small flush, foot sensor, ambient light | switch | Experimental, disabled by default |
| Water / seat / dryer temperature level, rear wash pressure, rear nozzle position, dryer fan speed, wide-wash level | number | Experimental, disabled by default (device levels, not °C) |
| Lid, Seat ring, Lid moving, Seat ring moving, Seated, Flushing | binary sensor | Read-only |
| Water shortage, Abnormal water flow, Sensor or overheat fault, Filter needs replacement, Foam liquid low | binary sensor | Read-only |
| Shower guard active | binary sensor | Read-only |
| Status, Filter remaining (%), Filter used (h), Front wash pressure / nozzle, Last refresh | sensor | Read-only |
| Raw E2 / FA / E9 / EA / E7 | sensor | Diagnostic, disabled by default |

*Verified* means the command was sent to a real ZS800J and the result was confirmed by
reading the device back, with every other setting unchanged. *Experimental* encodings
follow the same frame layout but have not yet been exercised on hardware; they still
read back and refuse to report success unless the device confirms it.

The ring and lid are linked on this model: opening the ring also opens the lid; closing
the ring leaves the lid open. The automatic lid opening sensor reacts to a person
standing in front of the toilet, so a lid you just closed may reopen if someone is there.

## Shower guard

Import the blueprint:

[![Open your Home Assistant instance and show the blueprint import dialog.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fxiaoyaner0201%2Fha-jomoo-ble%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fjomoo_ble%2Fshower_guard.yaml)

Inputs: a **hot-water-flowing** binary sensor, the toilet's *Automatic lid opening*
switch and a restore delay (default 3 minutes). Hot water on → suspend; hot water off for
the delay → resume. Each step retries up to 5 times, 30 s apart, until the
`guard_active` attribute shows the target.

Use a signal that means hot water is actually flowing, not just that the heater is
powered. Examples (adapt the entity ids):

```yaml
template:
  - binary_sensor:
      # From a flow-rate sensor
      - name: Hot water flowing
        state: "{{ states('sensor.water_heater_flow') | float(0) > 0 }}"
        delay_off: "00:00:20"
      # Or from a heater entity that reports burner activity
      - name: Hot water flowing (burner)
        state: "{{ state_attr('water_heater.my_heater', 'heating') in [true, 1, '1'] }}"
        delay_off: "00:00:20"
```

Tested pairing: the maintainer's China-market A.O. Smith gas water heater, added through
the community [Ai-Link A.O. Smith](https://github.com/mopocv/Ai-Link_A.O.Smith)
integration (v1.4.0 or newer, which renews its short-lived app token by itself). Its
*burner heating* sensor (`heating`) is the trigger:

```yaml
state: "{{ is_state('sensor.<heater>_ran_shao_jia_re_zhuang_tai', '加热中') }}"
```

Prefer burner state over flow rate there: the flow reading was non-zero once while no
tap was open.

Guard semantics: suspend remembers the current value and only writes *off* if it was on;
resume only writes *on* if it was on before, and never writes *off*. Changing the switch
by hand while the guard is active cancels the guard, so your manual choice wins. The
guard state survives restarts.

## Safety model

- Before any write, the integration reads E2, FA, E9 and EA in the same connection and
  refuses unless the toilet is in standby. Lid, ring and flush commands are also refused
  while someone is seated or while the lid or ring is moving.
- Every control frame carries the full settings block. It is rebuilt from that fresh
  read, so nothing else changes. After the write, the integration reads back until the
  target is confirmed. It then compares every other known setting and raises with a
  before/after diff if anything else moved.
- Flush commands report "sent, unconfirmed" (logged warning) if the flushing flag is not
  seen within about 6 seconds.
- Writes are **never retried automatically**: a failed write may still have reached the
  toilet. No optimistic state is published.
- If a disconnect cannot be confirmed, the integration stops connecting until reloaded.
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

To repeat the isolated HA candidate checks, run the official 2026.9.1 image with
`--network none --memory 2g --cpus 2 --rm`, mount this checkout read-only at `/repo`,
and execute `python3 /repo/tests/ha_smoke/smoke_in_ha_container.py /repo`.
Repeat with `--uncertainty` after `/repo` to test conservative failed-unload behavior.
Do not mount a production config or Bluetooth hardware.

```sh
python -m unittest discover -s tests -v   # protocol + synthetic BLE + shower guard
python scripts/sync_library.py --check    # bundled lib/ identical to jomoo_ble/
python scripts/check_repository.py        # compile, links, no real MAC / private IP
ruff check . && ruff format --check .
```

`tests/ha_smoke/smoke_in_ha_container.py` runs the whole integration (config flow,
entities, services, shower guard, options, diagnostics, unload) inside a real Home
Assistant Python environment against a fake toilet. Never point it at a production
config directory. Protocol details: [docs/protocol.md](docs/protocol.md). Verification
record: [docs/verification.md](docs/verification.md).

## Disclaimer

Unofficial and not affiliated with or endorsed by JOMOO. JOMOO and Home Assistant are
trademarks of their respective owners. The implementation is original. No vendor code,
mini-program package or asset is included or needed. Use at your own risk.

## License

[Apache-2.0](LICENSE)
