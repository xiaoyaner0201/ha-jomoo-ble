# Verification record

This record keeps three layers of evidence separate: offline tests, a real Home
Assistant runtime, and physical hardware.

## Offline (CI)

- `python -m unittest discover -s tests -v` covers protocol, sessions and guard;
  the stream candidate adds synthetic acquisition/lifecycle tests (exact executed count
  and interpreter versions are recorded in its delivery report).
  - Every decoder is checked against the hardware fixtures.
  - All seven verified function-frame vectors are reproduced byte for byte.
  - A single-field change only touches its own bits.
  - Read-only fields and out-of-range values are refused, and option frames are covered.
  - Session gates are checked: busy, seated, moving or in-transit states are refused;
    an unrelated setting change raises with a diff; an unconfirmed action or flush is
    reported as such; a failed write is not retried.
  - Disconnect uncertainty blocks further connections, and the lock serialises sessions.
  - The shower-guard truth table is covered, including a failed suspend that keeps the
    original value, so a retry cannot record "was off" by mistake.
- `scripts/check_repository.py` compiles every source, parses JSON and checks local
  links. It also rejects any non-fictional MAC address, private IPv4 address, private
  path or vendor package.
- `scripts/sync_library.py --check` confirms the bundled `lib/` is byte-identical to
  the canonical library.
- `ruff check .` and `ruff format --check .` pass.

## Home Assistant runtime (real HA 2026.9.1 container, isolated temp config, fake toilet)

`tests/ha_smoke/smoke_in_ha_container.py` checks the following:

- The manifest and Bluetooth matcher load, and en / zh-Hans translations resolve
  (54 entity strings each).
- A config flow with a bad MAC returns the form error; a valid one creates the entry
  with a single connection.
- Setup makes no extra connection. Entities start as *unknown*, not unavailable.
- The Refresh button fills lid, ring, filter (91.6 %), work status (standby), seated and
  last refresh.
- With controls disabled, the guard service is refused. With controls enabled, the
  options flow rejects a poll interval of 60 and accepts 0.
- Shower guard:
  - `suspend_auto_cover` writes the verified *off* frame, giving
    `guard_active: true, guard_previous: true`;
  - `resume_auto_cover` writes the verified *on* frame and clears the guard.
- The open-lid and small-flush buttons are confirmed by read-back.
- The `jomoo_ble.refresh` service connects once.
- Diagnostics redact the address, and unload succeeds.

## Opt-in stream candidate (offline and HA container only)

See [status-stream.md](status-stream.md) for semantics and the tests added for the candidate.
The stream implementation itself has not contacted physical hardware or production HA.
The earlier 90-second passive observation is protocol evidence, not deployment acceptance.
Its unknown FA payload[5] bit0 remains unknown; there is no refill sensor or pump policy.

The extended smoke test uses the real HA 2026.9.1 coordinator, entities, services, options
and registry, faking only BLE discovery/establishment and device traffic. It also fixes
old smoke entity lookups that matched `last_refresh` instead of the Refresh button and
`auto_small_flush` instead of the small-flush button. Assertions now target actual buttons.
Stream tests assert startup/no polling, off/on/off, timestamps, one physical client,
guard preservation, loss/unavailability, coalesced recovery, failed startup without a
scheduled retry, option release, stable IDs, entry restart with retained options, unload and HA stop.
A second `--uncertainty` run verifies failed physical release retains ownership,
marks HA FAILED_UNLOAD, blocks reload/control, and exposes the diagnostic.
These are synthetic assertions, not real proxy or toilet results.

## Hardware (one ZS800J, ESPHome proxy beside the toilet)

Verified with read-back and with all other settings unchanged:
- status query;
- open and close lid;
- open and close seat ring;
- small flush (also heard by the owner);
- automatic lid opening off and on.

## Production Home Assistant (HA 2026.9.1, same toilet and proxy)

- Bluetooth discovery found the toilet; the confirm step's one read-only check succeeded.
- `Refresh status` returned standby, lid and ring closed, automatic lid opening on,
  filter 91.6 %.
- With controls enabled, `jomoo_ble.suspend_auto_cover` was run once via the HA service API.
  The first attempt wrote the off frame but never saw the E2 reply to the re-check, so
  the guard stayed *pending* while still remembering "was on". The client now re-sends
  the read-only query every 2 s within the timeout (actions are still never retried).
  After that fix the retried suspend confirmed off, and `resume_auto_cover` restored on
  and cleared the guard.

## Water-heater signal (same household)

- The A.O. Smith gas heater is in HA through Ai-Link A.O. Smith v1.4.0. The burner-state
  template drives the shipped blueprint, and the automation is live.
- The app token lasts 30 minutes. It was renewed and persisted at two consecutive expiries,
  and the coordinator kept succeeding every 60 s.

Not yet exercised on hardware: the experimental switches and numbers, large flush, and
a full shower (hot water on → guard active → off for 3 min → restored).
