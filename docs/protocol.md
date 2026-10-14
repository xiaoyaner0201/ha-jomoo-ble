# Wire evidence and conservative encoding

This specification contains protocol facts, not vendor source. Hex examples carry
no BLE MAC, IP, account, unique device address or household identifier.

## Envelope

`F3 F4 LEN SRC DST CMD PAYLOAD CHECKSUM FC`

- `LEN = total bytes - 4`; shortest frame is 8 bytes.
- Checksum: sum `LEN` through the last payload byte modulo 256.
- Source `0x92`, device `0x21`, query broadcast `0x00`.
- Responses were also observed to destinations `0x22` and `0x3A`; accept only
  observed device-source status layouts, never accept echoed control/query frames.
- FFE1 uses notify and write-without-response, not a GATT write-with-response ACK.

Read-only semantic queries:

```text
E2: f3f4089200e2000000007cfc
E7: f3f4089221e700000000a2fc
```

Known response payload sizes: E2=7, EA=13, E9=6, FA=8, E7=4. The decoder validates
framing, checksum, routing and command-specific size. E7 filter fields and FA
extensions remain raw diagnostic data, not guessed lifespan/temperature readings.

## EA mechanism evidence

In payload byte 0, lid position is bits 2–3, ring position bits 0–1. Position code
1 means closed, 2 means open; 0/3 remain unknown. Bit `0x40` indicates lid motion,
bit `0x20` ring motion. Other EA fields/bits have no setters or assigned meaning.

Observed first-byte examples: `05` both closed, `19`/`09` lid open, `1A` both open,
`55`/`49` lid moving, `75` both moving, `2A` ring moving. Bits `0x10`/`0x80` are not
used to infer positions. The E9 work code is payload byte 3; expose the raw code.

## Complete-profile write guard

Observed auto-cover E2 responses:

```text
on:  f3f40b2192e24a52b3450900003dfc
off: f3f40b2192e24252b34509000035fc
```

The matched settings were water level 4, seat level 2, air level 3, hip pressure 3 /
nozzle 5, woman pressure 4 / nozzle 5, auto flush enabled. These numbers are
**anonymized protocol-profile evidence**, not account/device identity.

The confirmed parameter payloads are `4a52b33000100000000000` (on) and
`4252b33000100000000000` (off). Action frames are 19 bytes (LEN=`0f`).

| Action | Selector | Read-back |
| --- | --- | --- |
| Open lid | `11` | EA lid open, motion stopped |
| Close lid | `10` | EA lid closed, motion stopped |
| Open ring | `13` | EA ring open, motion stopped |
| Close ring | `11` | EA ring closed, motion stopped; leaves lid open |
| Small flush | `0f` | Query status only, no physical completion claim |
| Auto cover off/on | `19` | E2 auto-cover state |

Verified automatic-cover commands:

```text
off: f3f40f9221194252b3300010000000000062fc
on:  f3f40f9221194a52b330001000000000006afc
```

**Why not decode every bit or generalize the settings encoder?** The handed-off
wire observations do not independently establish every parameter's arbitrary
encoding or every extended field's write behavior. A guessed universal encoder
could silently reset unrelated settings. Version 0.1 therefore matches the
**entire** E2 payload against the two profiles above and rejects any other bit
change for all actions. No partial/default-zero state is accepted. The literal
zero bytes are part of the verified full command profile, not invented unknown
settings. Other setting combinations need sanitized read-only/action evidence
before a mapping can be added. Never change a device to fit this gate.

For the accepted profile all known settings are preserved byte-for-byte; changing
auto cover affects only bit `0x08` and the checksum. Tests cover both initial
states and every action, corrupted checksums, malformed envelopes, chunking,
unknown layouts/profiles, motion and serialized current-query/write/read-back.

A query has no transaction ID. The client clears its in-session frame collection
for each fresh query, but cannot distinguish an arbitrarily delayed valid
notification from a solicited one. This remains a live acceptance limitation.
