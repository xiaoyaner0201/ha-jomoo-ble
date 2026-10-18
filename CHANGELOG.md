# Changelog

## 0.4.0

### Breaking changes

- Removed `jomoo_ble.suspend_auto_cover` / `jomoo_ble.resume_auto_cover`, the automatic
  lid switch's `guard_active`, `guard_pending`, `guard_previous` attributes and the
  Shower guard active binary sensor. Cross-device policy now belongs entirely in HA
  automations/scripts/blueprints; the integration exposes device capabilities only.
- Replaced the blueprint's `toilet` input with a generic `switches` list and HA-native
  scene snapshot/restore. Re-import/update it and edit or recreate existing automations.
- Unlike the removed policy, dynamic scenes do not survive HA restart or scene reload;
  manual changes during a pause do not cancel the saved snapshot restoration.
- **不兼容变更**：移除暂停/恢复服务、守护属性和「淋浴守护生效中」传感器。
  跨设备策略移至 HA 自动化/脚本/蓝图；旧蓝图需更新，并将 `toilet` 改为 `switches`。
  动态快照无法跨 HA 重启或场景重载保留，手动改开关不再取消恢复。

### Added

- Best-effort cleanup of obsolete guard storage and its sensor registry entry.
  An active/pending old pause produces one setup warning to check Automatic lid opening.
  Cleanup never connects to or writes the device.
- Real-HA migration and blueprint tests, including original off-state preservation,
  re-trigger protection, per-switch failure isolation and dropped-timer recovery.

### Changed

- Foot sensor is a hardware-verified configuration switch, enabled in the entity registry
  by default and gated by `enable_controls`, not `enable_experimental`. ZS800J / HA
  2026.9.1 read-back confirmed FA p7 `0x33` → `0x13` → `0x33`, other settings unchanged.
  Its unique ID and existing entity ID remain unchanged. Only an old integration-disabled
  default is re-enabled; user disables are respected. Display name is Foot sensor / 脚感.
- The HA-native blueprint snapshots selected switches once, attempts all-off up to 5
  times 30 s apart, then restores the original values and deletes the dynamic scene.
  Default restore delay is now 10 minutes. Restore waits until every selected switch
  is available, so a Bluetooth drop cannot delete the snapshot without restoring it.
  HA-start / 5-minute recovery works only if
  the scene still exists. `scene.delete` is available in HA 2026.9.1.
- 脚感升为已验证控制，注册表默认启用，保留实体 ID 与用户禁用选择；蓝图改用 HA 原生快照/恢复，默认延迟 10 分钟；所选开关全部可用后才恢复，蓝牙掉线不会丢掉快照。

### Removed

- The integration's persistent shower-guard policy, library modules, entity services,
  diagnostic block and remembered-state sensor/attributes. Device command safety,
  no-retry transport writes and optional live-status lifecycle remain unchanged.

### Migration

1. Stop the old automation and check/restore a currently paused lid setting before
   upgrading. Replace the complete component directory (including `lib/`) and restart HA.
   Setup discards old memory without restoring the device.
2. Enable verified controls, re-import the blueprint at its original path, select
   Automatic lid opening and Foot sensor in `switches`, and reserve a unique `scene_id`.
3. Delete/replace service-based automations and old fallbacks referencing the removed
   sensor or guard attributes. Verify both initially-on and initially-off values restore.
4. For restart-proof restoration, implement a persistent `input_boolean` per switch in
   your own automation, or check switches manually after an interrupted pause.
5. 升级前检查暂停中的自动翻盖；更新后重新导入蓝图并选择自动翻盖和脚感；删除旧服务调用和守护兜底。
   跨重启恢复需逐开关持久辅助实体，或人工检查。完整迁移步骤见中英文 README。

## 0.3.0

- Added opt-in persistent live status (`enable_status_stream`), disabled by default.
  One shared BLE connection receives passive notifications for existing entities,
  including flushing, without periodic queries. Refresh, controls and shower guard
  share the connection and operation lock; control writes still require fresh reads,
  a single write, read-back and unchanged-setting checks.
- Added live-connection and last-received diagnostics, per-frame receive timestamps,
  conservative loss/unavailability handling, explicit coalesced manual recovery and
  connection release on option disable, unload or HA stop. No automatic reconnect loop.
- Fixed a stale disconnect latch across connection handoff, so an early transport loss
  cannot leave an adopted connection incorrectly marked healthy.
- Recorded live HA 2026.9.1 / ESPHome proxy acceptance: 5 hardware scenarios, including
  stream re-establishment after an HA restart during an automation pause; about 10.5
  hours on one uninterrupted connection and all 9 daily flush on/off cycles received,
  with no unavailable flushing/seated entities. A separately maintained HA-native
  refill automation (not shipped here) acted about 0.5 seconds after flushing ended.
  This does not identify a refill-complete bit or prove long-term stability.
- Expanded synthetic BLE and real-HA container lifecycle coverage, including failed
  unload and connection-handoff loss; updated live-status documentation and limits.
- Docs: corrected the tested A.O. Smith hot-water signal. The burner-state sensor never
  changed during a real shower; the working trigger is zero-cold-water on or fan speed
  above 0, with a 10-minute restore delay.
- Docs: added a fallback automation that restores the guard after an HA restart or
  automation reload drops the blueprint's `for:` timer.
- Docs: ESPHome Bluetooth proxies need HA's scanning mode set to Active, or the toilet
  name never arrives and the device is refused after a reload.

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
