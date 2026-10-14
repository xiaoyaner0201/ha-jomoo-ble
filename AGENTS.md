# Development boundaries

- This is an original clean-room implementation based on wire-level facts.
- Never import/copy vendor source or packages; protocol observations are not vendor code.
- Do not contact a live toilet, proxy, Home Assistant instance, or heater during tests.
- Do not add credentials, personal identifiers, private paths, or unredacted captures.
- Preserve every mapped setting before a control write; reject unmapped profiles.
- Never retry an actuator write or claim success without device read-back.
- `jomoo_ble/` is canonical; run `python scripts/sync_library.py` after editing it.
- `custom_components/jomoo_ble/lib/` is the identical bundled copy for manual installation.
- Run `python -m unittest discover -s tests -v`, `python scripts/check_repository.py`,
  `python scripts/sync_library.py --check`, and `ruff check .` before committing.
- Protocol and synthetic transport tests do not prove Home Assistant/live BLE success.
- Read [README.md](README.md) and [docs/protocol.md](docs/protocol.md) for evidence and limits.
