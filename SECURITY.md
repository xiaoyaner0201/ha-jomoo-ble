# Security and safety

This integration operates local BLE actuators. There is no account/cloud integration
or arbitrary raw-write service. Controls are opt-in, experimental controls need a
second opt-in, and every write is rebuilt from a fresh read and verified afterwards. Device names and BLE addresses are not authentication.
The protocol does not provide cryptographic origin/integrity protection.

Keep Home Assistant and proxies patched, restrict proxy/network access, and
avoid public HA exposure. Single-central contention, disconnect failures and
ambiguous write completion can make a retry unsafe. Inspect hardware first.
Do not rely on this component for occupant detection or mechanical safety.

Do not publish credentials, Bluetooth addresses, proxy addresses, account IDs,
private cache paths, captures with identifiers, or vendor packages in reports.
Use fictional addresses and sanitized wire payloads instead. Consider status
history sensitive because it can reveal usage patterns.

Report suspected vulnerabilities privately through GitHub's "Report a vulnerability"
(security advisories) on https://github.com/xiaoyaner0201/ha-jomoo-ble rather than a
public issue. Do not send reports to JOMOO or Home Assistant as if they maintain this
project. No support SLA is promised.

The shower guard must be driven by a signal that means hot water is actually flowing;
it preserves the prior setting and yields to manual changes.
