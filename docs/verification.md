# Verification record

Evidence is separated into offline tests, a real Home Assistant runtime with a fake
BLE device, and previously supplied physical-device acceptance. Container tests do
not prove physical Bluetooth/proxy behaviour. No new live-system test was run for
this refactor.

## 0.4.0 — current verification

### Offline checks

- `python -m unittest discover -s tests -v`: **60 tests pass**. Existing protocol,
  transport and stream coverage is retained; tests for the deleted policy module are
  removed. New foot-sensor cases cover off/on read-back (`0x33` → `0x13` → `0x33`),
  already-at-target no-op, unrelated-setting rejection, unconfirmed writes and no retry
  after write failure.
- Decoders use sanitized hardware fixtures; function-frame vectors round-trip exactly.
  Single-field changes only touch their own bits. Read-only/out-of-range fields,
  E2/FA disagreement, busy/seated/moving states, ambiguous flush completion, missing
  frames, disconnect uncertainty and concurrent sessions remain covered.
- Stream tests retain full initial-query/freshness gates, no cached control settings,
  shared connection ownership, handoff loss, cancellation, failed release and explicit
  coalesced manual recovery. No periodic queries or automatic reconnect loop is added.
- `python scripts/check_repository.py`: compile, JSON metadata, local links and public
  artifact hygiene pass (**25 Python sources**). `python scripts/sync_library.py --check`
  confirms the bundled library is byte-identical to the canonical library.
- Ruff **0.15.4**: `ruff check .` and `ruff format --check .` pass.
  `git diff --check` passes.

### Real HA 2026.9.1 container

All three invocations of `tests/ha_smoke/smoke_in_ha_container.py` exit **0**: normal,
`--uncertainty` and `--handoff`. Each uses the official HA 2026.9.1 image, a read-only
repository mount, temporary configuration, `--network none --memory 2g --cpus 2 --rm`,
and no production config, credentials or Bluetooth devices.

The real config/options flows, integration, coordinator, entities, services, entity
registry and storage are exercised. Only physical BLE discovery/establishment and
traffic are faked. Assertions cover:

- Invalid address and poll interval handling, one read-only config-flow connection,
  no extra default setup connection, Refresh button/service, mechanical/flush read-back,
  diagnostics address redaction and unload. Both locales resolve **53 entity strings**.
- **Migration of removed policy APIs:** both former suspend/resume services are absent,
  no guard attributes or remembered-state sensor is exposed, and diagnostics contain
  no policy block. Active and pending obsolete stores each produce exactly one setup
  warning, are removed through HA Store, and do not cause BLE connections/writes.
  Missing stores are silent; read/remove I/O failure cannot prevent setup. Config-entry
  deletion also cleans storage. The stale policy sensor registry entry is removed.
- Foot sensor is a normal CONFIG switch, enabled in the registry by default and available
  with verified controls on / experimental controls off. The unique ID/entity ID stays
  unchanged. An integration-disabled default is re-enabled; a user disable is retained.
  Both verified switches call the ordinary command path, and the controls gate refuses
  direct calls when disabled.
- Persistent-stream startup uses read-only full queries and one physical client. Passive
  flush off/on/off, receive timestamps, silence, shared commands/refresh, loss and manual
  recovery, option disable, stable IDs, failed startup without scheduled retry,
  entry re-creation with retained options and HA stop all remain asserted.
- `--uncertainty`: failed physical release retains ownership, marks HA FAILED_UNLOAD,
  refuses reload/control and exposes diagnostics. `--handoff`: authoritative loss before
  adoption releases the client, leaves HA off/unavailable, blocks writes/reconnect and
  permits explicit recovery; stale callbacks cannot contaminate the recovered client.

### HA-native blueprint

`tests/ha_smoke/blueprint_scenario.py` imports the published YAML through HA's own
blueprint loader and validates the expanded automation with the real HA validator.
Both the default **10-minute** delay and a short test delay validate. The runtime
reports:

```text
scene.delete exists in HA 2026.9.1: registered by homeassistant.scene
blueprint validation PASS: imported, default 10 min and short-delay automation config valid
blueprint scenario PASS: foot originally on, snapshot preserved, restored, scene deleted
blueprint scenario PASS: foot originally off, snapshot preserved, restored, scene deleted
blueprint partial failure PASS: other switch paused, hot-water off interrupted retry wait
blueprint recovery PASS: lost off timer restored while snapshot exists
```

A core input_boolean/template binary sensor supplies hot-water state; the fake toilet's
real integration switches supply target states. Hot water on creates a snapshot and
turns both switches off. Re-triggering cannot overwrite the original values. Off for
0.1 s restores them, including an originally-off foot sensor, then deletes the scene.
A failed first switch does not block the other; hot-water off interrupts the retry
wait. Disabling/re-enabling the automation drops its off timer; directly invoking the
same recovery action branch restores an existing scene. This is **not** an assertion
that a restart preserves a scene, nor a wall-clock five-minute recovery test.

Dynamic scenes are memory-only: HA restart or scene reload loses the snapshot. The
blueprint cannot automatically restore a pause interrupted that way. Use persistent
helpers per switch for restart-proof memory, or inspect the switches manually. Scene
restoration is best effort, not transactional, and manual changes do not cancel it.

### Foot sensor hardware evidence (supplied acceptance)

On a ZS800J with HA 2026.9.1, the SUB `0x24` option was verified off → on with read-back:
FA p7 `0x33` → `0x13` → `0x33`, every other setting unchanged. This supports promotion
of **Foot sensor / 脚感**, not other option writes or other toilet models. The 0.4.0
container/offline checks are separate regression evidence, not a new hardware session.

## History — pre-0.4.0 runtime and policy acceptance

The earlier integration had its own persistent pause/restore policy, exercised in
synthetic tests and a real HA 2026.9.1 runtime with a fake toilet. Historical physical
acceptance also confirmed the policy's off/on frames. One first write landed but lacked
an E2 reply; resending read-only queries within the timeout fixed verification without
retrying actuator writes. Retrying the old policy then confirmed off and restored on.
These records describe **removed behaviour**, not the 0.4.0 architecture or guarantees.
The earlier translation count was 54 per locale, before removal of its policy sensor.

## History — opt-in stream hardware acceptance (HA 2026.9.1, ESPHome proxy)

See [status-stream.md](status-stream.md) for current acquisition semantics.

- Explicitly enabling persistent status delivered flush start/end via passive
  notifications without periodic queries.
- All 5 end-to-end hardware scenarios passed, including stream re-establishment after
  an HA restart during an automation pause. This proves stream re-establishment only,
  **not** preservation of the new blueprint's snapshot across restart.
- After the final installation, one connection stayed up about 10.5 hours without
  disconnects. All 9 daily flushes delivered on → off; Flushing and Seated never became
  unavailable in that window.
- A separately maintained HA-native refill automation, not shipped here, acted about
  0.5 seconds after flushing ended. This validates an external consumer of `flushing`,
  not a refill-complete bit. FA payload[5] bit0 remains unknown; no refill sensor exists.
- A preceding 90-second passive observation was protocol evidence, not implementation
  acceptance. The handoff disconnect latch was fixed in `99d9692` with offline/HA
  regression tests; these do not simulate every physical proxy/phone failure.
- Long-term stability remains under observation. Single-central ownership, a beep per
  connection, no heartbeat and manual checks/restart after uncertain release remain
  limitations. HA 2026.9.1 refuses reload after FAILED_UNLOAD.

## History — initial hardware and HA acceptance

One ZS800J with a nearby ESPHome proxy verified read-only status, lid open/close,
seat-ring open/close, small flush and automatic lid opening off/on, with read-back and
all other settings unchanged. HA discovery and a single read-only setup check succeeded;
Refresh returned standby, lid/ring closed, automatic lid opening on and filter 91.6 %.
Experimental switches/numbers and large flush remain unverified on hardware.

## History — corrected hot-water signal

An A.O. Smith gas heater was integrated through Ai-Link A.O. Smith v1.4.0. Its 30-minute
app token was renewed/persisted at two consecutive expiries and queries continued every
60 s. The earlier recommended burner-state signal did not change during a shower
(about 3000 rpm fan, 44% burner duty, 42 °C outlet). The corrected signal is
**zero-cold-water on or fan speed above 0**, verified on recirculation start/stop, with
**10-minute** restoration delay. A full corrected-signal shower cycle has not been
recorded. An automation reload dropped the old off timer; a separately configured
fallback restored the old policy. That fallback is obsolete in 0.4.0: use the new
blueprint's recovery while its scene exists, respecting the restart limitation.

## History — Bluetooth proxy scanning mode

After HA reload, a strong advertisement lacked the model name because HA's ESPHome
entry used Auto scanning (passive most of the time). The integration correctly refused
an unsupported advertised model. Setting HA-side scanning to **Active** delivered
`JOMOO_SMART_237369` and allowed Refresh. ESPHome YAML `active: true` alone does not
override HA's scanning mode.
