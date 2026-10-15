# Changelog

## 0.2.0

- Full decoders for status frames E2, FA, E9, EA and E7. Unknown bits are kept raw.
- A general function-frame encoder replaces the exact-profile gate. It is built from a
  fresh E2 and FA read, and reproduces every hardware-verified vector byte for byte.
- Safety gates:
  - writes are refused unless the toilet is in standby, nobody is seated and the lid and
    ring are not moving;
  - after a write, the target is read back, and all other settings are diffed;
  - flush commands report "sent, unconfirmed" when the flushing flag is not observed.
- No BLE connection at start-up and no polling by default (each connection beeps).
  Instead there is a Refresh button and a `jomoo_ble.refresh` service; slow polling is
  optional.
- Shower guard:
  - `suspend_auto_cover` and `resume_auto_cover` entity services, persisted across
    restarts;
  - they restore exactly the previous automatic lid opening value;
  - plus an automation blueprint.
- New entities: seated, flushing, faults, filter remaining and used, foam low, work
  status, last refresh.
- Experimental switches and numbers, behind a separate option.
- Bluetooth discovery, en and zh-Hans translations, diagnostics with the address
  redacted, `hacs.json`, `services.yaml`.
- A smoke test that runs inside a real Home Assistant container against a fake toilet.

## 0.1.0: development preview

- Conservative first version: exact-profile writes, raw diagnostics, five verified
  buttons and the automatic lid opening switch.
