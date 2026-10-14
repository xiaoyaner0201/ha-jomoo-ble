# ha-jomoo-ble

[简体中文](README.zh-CN.md) · Apache-2.0 · Independent custom integration

Local Bluetooth control for the **JOMOO ZS800J** smart toilet, through Home
Assistant Bluetooth and connectable BLE proxies. This is a development preview,
not an official JOMOO integration or a claim of Home Assistant live acceptance.

**Safety limit:** the first release only writes against the complete settings
profile observed in the verified command transcripts. Other profiles remain
read-only. It does not guess missing settings, fill them with defaults, or let an
automatic-cover change reset temperatures, pressure, nozzle positions or auto flush.

## Exact-model evidence and development provenance

The official **九牧智联 (JOMOO Smart)** WeChat mini program's model routing mapped
model code **237369 → ZS800J / bleProtocol0**. The corresponding advertisement uses
the `JOMOO_SMART_` family prefix and that model-code suffix. The code is model
evidence, not a unique device identifier or BLE authentication mechanism.

Development originally used the owner's authorized **official mini-program
cache** to understand model selection and protocol behavior, then compared
read-only responses and reversible actions on the exact device. This did not
establish that macOS WeChat's UI can control the device. Wire facts and anonymized
acceptance transcripts were handed to this implementation; all repository code
was independently written. No vendor JavaScript, extracted package, private
cache, account data or application assets are included or needed to run it.

Prior exact-device evidence, **separate from this integration's acceptance**:

- FFE0 service / FFE1 notify + write-without-response control channel.
- `F3 F4` frame envelope, source `0x92`, toilet `0x21`, broadcast `0x00`.
- E2 state query and E7 filter query returned valid status frames.
- Open/close lid, open/close seat ring, small flush, and auto-cover off/on were
  exercised on the device. Cover/ring position and auto-cover settings were read
  back; small flush was physically observed, not inferred from a BLE write ACK.
- ZS800J lid/ring state comes from **EA**, not E2 or a sibling model's decoder.

These findings do **not** establish support for every JOMOO model, firmware,
pressure/temperature combination or proxy. See [protocol evidence](docs/protocol.md).

## Installation and configuration

1. Back up your HA configuration. Copy **the entire**
   `custom_components/jomoo_ble` directory, including `lib`, into the matching
   `custom_components` directory in your Home Assistant configuration. Restart HA.
   The standalone wheel contains only the protocol library, not the HA component.
2. Enable the built-in **Bluetooth** integration. For a remote ESPHome proxy,
   enable active BLE connections; a passive scanner cannot control the toilet.
   This component uses HA's selected connectable device/backend; it does not
   connect to a proxy IP directly or need proxy credentials of its own.
3. Place the proxy near the toilet with reasonable radio coverage. Distant weak
   advertisements do not imply reliable connections. Avoid a wet enclosure and
   mains wiring; do not put an unprotected proxy inside the toilet.
4. Disconnect/close the official mini program first. Only **one BLE central** can
   connect at once. Connections can make the toilet beep; choose an appropriate
   polling interval (default 60 seconds; options allow 30–3600 seconds).
5. Add **JOMOO BLE** in Settings → Devices & services. Enter your actual BLE MAC
   locally and keep the default name prefix `JOMOO_SMART_`. A valid *fictional*
   address is `02:00:00:00:00:01`; do not use that example as your device address.
   A macOS CoreBluetooth UUID is not a MAC. Unsupported advertised model codes
   are rejected. Setup performs read-only queries and then disconnects.
6. Verify the read-only entities against the official app/remote first. Controls
   are **disabled by default**. Enable them in integration options only with
   someone present and a clear mechanism. If the verified-profile diagnostic is
   off, write controls remain unavailable; do not change your device settings
   merely to bypass the guard.

No public repository or HACS listing has been assumed in the manifest. Its
documentation URL points to HA's Bluetooth prerequisites; project documentation
is here. Maintainer identity, project URLs and release/HACS publication remain
separate release decisions.

## Entities

| Type | Surface | Limits |
| --- | --- | --- |
| Sensors | Water/seat/air temperature **levels**, hip/woman pressure levels and nozzle positions | No °C inference. Values are exposed only when the complete verified E2 profile matches. |
| Sensor | E9 work-status code | Raw code; no unverified washing/flush mode labels. |
| Diagnostic sensors | Raw E2/E7/FA/E9 payloads | Disabled by default. Filter-life units/percentage are not yet mapped. |
| Binary sensors | Lid open, seat ring open, lid moving, ring moving | EA read-back; unknown position stays unknown. |
| Binary sensors | Automatic flush setting; verified parameter profile | Auto flush is read-only. |
| Switch | Automatic cover on/off | Only the verified setting is writable. |
| Buttons | Open lid, close lid, open seat ring, close seat ring, small flush | Fresh state required; no optimistic state. |

Opening the ring also opens the lid on the verified model. Closing the ring
leaves the lid open. The observed `0x11` selector is shared by lid-open and
ring-close; an already-open lid request is a no-op to avoid closing an open ring.
There is no fabricated “flush succeeded” sensor.

## Write safety and connection lifecycle

Polling and actions share one lock and one short-lived connection. A command
queries fresh **E2 and EA in the same session**, checks known mechanism positions
and motion, and validates the complete supported E2 settings profile. Settings
are preserved from the matching verified profile, not from stale HA state.
The encoder changes only the action selector, or selector `0x19` plus auto-cover
bit `0x08`. Every other parameter byte is preserved. Any other E2 bit change
refuses the write rather than inventing a mapping.

After writing, the session queries again and only publishes actual received
state. Lid/ring actions require the target position with motion stopped;
auto-cover requires the matching E2 bit. Small flush is sent once followed by
status retrieval, **not** a physical completion ACK. Failed/unconfirmed writes
mark entities unavailable, are not retried, and may still have reached hardware.
Inspect the device before retrying. Connections are disconnected in `finally`,
including cancellation. Uncertain disconnect blocks new connections until reload.

BLE has no transaction ID here. Delayed notifications, notification ordering,
mechanical safety interlocks and unreported settings need further exact-device
acceptance. This code is not an occupancy-based safety system or a replacement
for device protections. Occupancy is not exposed because its bit mapping was
not independently established for this release.

## Hot-water automation goal — linkage pending / 联动待接入

The intended automation is:

1. When the water heater is **actually delivering hot water**, save the current
   automatic-cover setting and turn automatic cover off.
2. When hot-water delivery stops, restore **the saved prior setting**, not always
   “on”. If it was off before, it must remain off.

**The water heater is not connected by this project. Linkage is pending.**
Heater power, a hot tank, or a temperature threshold is not proof of hot-water
flow. No heater entity, invented sensor, or ready-to-run household automation is
included. A future linkage must validate a real flow/heating signal, deal with
restarts and unavailable states, debounce flow, preserve manual overrides and
avoid replaying a physical command after an uncertain failure.

## Not supported / not claimed

No washing, drying, large flush, temperature/pressure/nozzle setters, night-light
setter, factory reset, activation, identity writes, firmware update/OTA, cloud
login, or arbitrary command service is implemented. An observed status field
does not imply its setter is safe. Other models (including unrelated `5A` or
`FFA0` protocols) are not supported. Do not import raw vendor packages into this
repository to extend it.

## Local development and verification

The pure protocol and synthetic-session tests need only Python's standard
library. No HA server, radio, account or production configuration is used:

```sh
python -m unittest discover -s tests -v
python scripts/sync_library.py --check
python scripts/check_repository.py
ruff check .
```

`check_repository.py` runs `py_compile` on every Python source, parses JSON,
checks local Markdown links and basic public-data hygiene. CI repeats the tests
on Python 3.10, 3.13 and 3.14. `jomoo_ble` is the canonical library;
`scripts/sync_library.py` produces the byte-identical copy bundled in the custom
component. Change the canonical source first, then synchronize it.

Passing these checks proves only offline code/fixture behavior. A real Home
Assistant config flow, Bluetooth proxy connection and exact-device regression
remain acceptance gates for the deploying maintainer. See
[CONTRIBUTING](CONTRIBUTING.md), [SECURITY](SECURITY.md) and [CHANGELOG](CHANGELOG.md).
