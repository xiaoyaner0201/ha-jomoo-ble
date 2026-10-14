# Security and safety

This preview operates local BLE actuators. There is no account/cloud integration
or arbitrary raw-write service. Controls are opt-in and parameter writes reject
unmapped profiles. Device names and BLE addresses are not authentication.
The protocol does not provide cryptographic origin/integrity protection.

Keep Home Assistant and proxies patched, restrict proxy/network access, and
avoid public HA exposure. Single-central contention, disconnect failures and
ambiguous write completion can make a retry unsafe. Inspect hardware first.
Do not rely on this component for occupant detection or mechanical safety.

Do not publish credentials, Bluetooth addresses, proxy addresses, account IDs,
private cache paths, captures with identifiers, or vendor packages in reports.
Use fictional addresses and sanitized wire payloads instead. Consider status
history sensitive because it can reveal usage patterns.

Before a public issue about a suspected vulnerability, ask the distributing
maintainer for a private reporting channel without posting exploit details or
secrets. No public repository/contact has yet been assigned to this local
project; do not send reports to JOMOO or Home Assistant as if they maintain it.
Only the current preview is maintained; no support SLA is promised.

A future heater linkage must validate actual hot-water flow and preserve prior
state and manual overrides. It is not implemented here.
