# Verification scope

Local offline execution for this preview:

- Python 3.13: `python -m unittest discover -s tests -v` — **25 tests, OK**.
- Python 3.14: same command — **25 tests, OK**.
- `python scripts/check_repository.py` — **20 Python files passed py_compile**;
  JSON, relative documentation links and basic public-data hygiene passed.
- `python scripts/sync_library.py --check` — bundled library byte-identical.
- Ruff 0.15.4: `ruff check .` — **All checks passed!**
- `git diff --check` — no whitespace errors.

The transport is synthetic in the tests; no radio or Home Assistant server was
started. The known frame fixtures originate in prior exact-model evidence, not
in a claim that this new integration has been deployed.

An attempt to install Home Assistant 2026.10.0 in an isolated, credential-free
local virtual environment timed out during dependency retrieval. Home Assistant
API imports/config flow execution and hassfest have therefore **not been
verified** here. This blocker does not invalidate the standard-library tests or
syntax checks, and is not replaced with mocked “HA live success”.

Remaining acceptance gates: deploying maintainer's independent code review,
actual HA setup/unload and proxy routing, device/firmware profile regression,
filter/occupancy/arbitrary-setting mappings, and real heater hot-water flow
linkage. Publishing CI has not run on GitHub; only the local gates above have.
