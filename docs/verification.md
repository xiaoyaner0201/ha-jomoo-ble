# Verification record

This record keeps three layers of evidence separate: offline tests, a real Home
Assistant runtime, and physical hardware.

## Offline (CI)

- `python -m unittest discover -s tests -v` runs 38 tests on Python 3.13 and 3.14.
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
  (52 entity strings each).
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

- The A.O. Smith gas heater is in HA through Ai-Link A.O. Smith v1.4.0.
- The app token lasts 30 minutes. It was renewed and persisted at two consecutive expiries,
  and the coordinator kept succeeding every 60 s.
- Correction: the burner-state template recommended in 0.2.0 never fired. During the first
  real shower its sensor stayed "not heating" (fan about 3000 rpm, 44% burner duty, outlet
  42 °C), and the automation had never been triggered since it was created. The trigger
  was changed to "zero-cold-water switch on, or fan speed above 0". Applied while
  recirculation was running, the new signal turned on at once and triggered the
  automation, and it went off when recirculation stopped. The restore delay is now
  10 minutes. A full shower with the new trigger from start to finish has not been
  recorded yet.
- Saving the automation while hot water was already off dropped the running `for:`
  timer, so the guard was never restored. A periodic fallback automation (see README)
  then restored automatic lid opening by itself, and the guard cleared.

## Bluetooth proxy scanning mode

- After an HA reload, every entity became unavailable: the integration refused the toilet
  as "Unsupported advertised model". HA showed the advertisement at -63 dBm, but its name
  was the MAC address, because HA 2026.9 had left the ESPHome proxy in *Auto* scanning
  mode (passive most of the time). After setting the ESPHome entry's scanning mode to
  *Active*, the name `JOMOO_SMART_237369` arrived within a minute and Refresh succeeded.

Not yet exercised on hardware: the experimental switches and numbers, and large flush.
