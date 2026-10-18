# Contributing

Use Apache-2.0-compatible original code. Describe wire facts and evidence, not
copied vendor algorithms. Do not contribute extracted mini-program source,
packages, assets, private device identifiers, credentials or household details.

1. Work in an isolated branch/worktree. Start with offline regression tests.
2. Keep `jomoo_ble` independent of Home Assistant and radio dependencies. The integration
   exposes device capabilities only; cross-device policy belongs in HA automations or
   blueprints, not in the device coordinator or consumers of other integrations' entities.
3. Synchronize the bundled library: `python scripts/sync_library.py`.
4. Run `python -m unittest discover -s tests -v`,
   `python scripts/check_repository.py`, `python scripts/sync_library.py --check`,
   and `ruff check .`.
5. Review the full diff for safety and privacy. Distinguish offline fixtures,
   exact-device evidence, and HA end-to-end acceptance in the change description.

New model/setting mappings need exact model and protocol evidence plus sanitized
before/after full-state frames demonstrating that unrelated settings survive.
Do not expand control support on a sibling model's name alone. Never replay
actuator writes automatically. Always refuse unknown parameters rather than
invent defaults. Extended settings require explicit independent evidence.

Live testing is separately authorized work, never part of the offline suite.
Start read-only with the official app disconnected and a nearby proxy. Enable
one reversible setting, read back, restore the prior value, then check mechanical
controls with a person present. Flush requires explicit approval. Do not test
OTA, identity writes, activation or factory reset.

Maintainer: @xiaoyaner0201. Issues and pull requests: https://github.com/xiaoyaner0201/ha-jomoo-ble
