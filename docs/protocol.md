# ZS800J Bluetooth protocol notes

Written from wire observations on the maintainer's own toilet and from studying how the
official controller behaves. Nothing here is vendor code. Tags:

- **Verified**: observed on hardware with read-back.
- **App-derived**: how the official controller encodes or decodes it; not yet exercised
  on hardware by this project.
- **Unknown**: never written; kept raw.

Hex examples contain no device identifiers.

## Transport

- GATT service `FFE0`, characteristic `FFE1`: notify + write-without-response.
  **Verified**
- One central at a time. Each new connection makes the toilet beep. **Verified**
- The advertisement carries the local name `JOMOO_SMART_<model code>`; the ZS800J model
  code is `237369`. **Verified**

## Frame

`F3 F4 LEN SRC DST CMD PAYLOAD… CS FC`

- `LEN` is the total length minus 4.
- `CS` is the sum of `LEN` through the last payload byte, modulo 256. **Verified**
- Addresses: controller `0x92`, toilet `0x21`, broadcast `0x00`.
- Toilet frames may also be addressed to `0x22` / `0x3A` (other on-board controllers);
  any frame from `0x21` is accepted. **Verified**

## Queries

| Query | Frame | Answer |
| --- | --- | --- |
| Status | `f3f4089200e2000000007cfc` | E2, EA, E9, FA within ~1 s **Verified** |
| Filter | `f3f4089221e700000000a2fc` | E7 **Verified** |

## Status frames (payload byte `pN`)

### E2: settings (7 bytes)

`pN` is payload byte N, counted after the command byte.

| Byte | Bits | Field |
| --- | --- | --- |
| p0 | 4-6 | water temperature level |
| p0 | 3 | automatic lid opening (**Verified**) |
| p0 | 2 | gesture |
| p0 | 1 | automatic flush |
| p0 | 0 | night light |
| p1 | 4-6 | rear nozzle position |
| p1 | 0-3 | seat temperature level |
| p2 | 7 | automatic night light |
| p2 | 4-6 | rear wash pressure |
| p2 | 0-2 | dryer temperature level |
| p3 | 4-6 | front wash pressure |
| p3 | 0-2 | front nozzle position |
| p4-p6 | – | **Unknown** |

Example: `f3f40b2192e24a52b3450900003dfc` decodes to water 4, automatic lid opening on,
automatic flush on, rear nozzle 5, seat 2, automatic night light on, rear pressure 3,
dryer 3, front pressure 4, front nozzle 5.

### FA: extended settings and live flags (8 bytes) **App-derived layout, Verified values**

| Byte | Field |
| --- | --- |
| p0 | same as E2 p0: water temperature, automatic lid opening, automatic flush |
| p1 | bit 7 smart power save; bits 4-6 rear nozzle; bits 0-2 seat temperature |
| p2 | same as E2 p2 |
| p3 | bits 4-7 front pressure; bits 0-3 front nozzle |
| p4 | bit 3 large flush running; bit 2 small flush running (**Verified**: `0x11` → `0x15` during a small flush); bit 1 close lid before flush; bit 0 automatic deodorisation; bits 4-6 dryer fan speed |
| p5 | bit 5 UV water disinfection; bit 4 ambient light; bit 3 seasonal temperature; bits 6-7 ambient light mode; bit 0 **Unknown** |
| p6 | bit 6 add-liquid box; bit 5 pre-wetting; bit 4 open-loop foam; bit 3 automatic foam; bit 2 foam running; bit 1 filter insufficient; bit 0 filter reminder |
| p7 | bits 6-7 foam liquid (`00` low, `11` sufficient, other unknown); bit 5 foot sensor; bit 4 automatic small flush; bits 0-2 wide-wash level (0 treated as 1) |

### E9: runtime (6 bytes) **App-derived layout, Verified standby values**

| Byte | Field |
| --- | --- |
| p0 | bit 7 seated; bit 5 deodoriser running; bits 3 and 6 **Unknown** (bit 3 tracks the lid on this unit, but EA is the authoritative source) |
| p1 | bit 7 water shortage; bit 6 or bit 3 abnormal flow; bit 5 outlet overheat; bit 4 inlet overheat; bit 2 outlet sensor fault; bit 0 inlet sensor fault |
| p2 | bit 5 seat overheat; bit 1 seat temperature error; bit 0 ambient sensor fault |
| p3 | work status: 1 or 2 standby; 3 nozzle cleaning; `0x83` nozzle replacement; `0x10` / `0x90` drying; bit 5 rear wash; bit 6 front wash |
| p4 | bit 3 automatic mode |

### EA: lid and seat ring (13 bytes) **Verified**

p0 holds the lid and ring state:

| Bits | Field |
| --- | --- |
| 2-3 | lid: `01` closed, `10` open, other = in transit |
| 0-1 | ring: same coding |
| 6 | lid moving |
| 5 | ring moving |
| 4, 7 | **Unknown**; seen in every state, ignored |

Observed p0 values:

| p0 | Meaning |
| --- | --- |
| `05` | both closed |
| `09` / `19` | lid open |
| `1a` | both open |
| `55` / `49` | lid moving |
| `75` | both moving |
| `d0` | in transit |

### E7: filter (4 bytes) **App-derived formula, Verified values**

- Used hours = `((p3 >> 6) << 8) | p2`; used minutes = `p3 & 0x3F`.
- Rated life is 13 980 minutes, so remaining % = `100 × (13980 − used) / 13980`.
- Example: `f3f4082192e701c3131c95fc` → 19 h 28 min used → 91.6 % remaining.

## Control frames

### Function frame (19 bytes): `F3 F4 0F 92 21 OP b6 … b16 CS FC`

The frame always carries the complete settings block, so it must be built from a fresh
read. The encoder takes E2 and FA from the same connection, refuses if they disagree, and
changes only the requested field.

| Byte | Content |
| --- | --- |
| b6 | `water<<4 \| auto_lid<<3 \| gesture<<2 \| auto_flush<<1 \| night_light` |
| b7 | `power_save<<7 \| rear_nozzle<<4 \| seat` |
| b8 | `auto_night_light<<7 \| rear_pressure<<4 \| dryer` |
| b9 | `wide_wash<<4` |
| b10 | 0 |
| b11 | `fan_speed<<4` |
| b12-b16 | 0 |

| OP | Action | Status |
| --- | --- | --- |
| `10` | close lid | **Verified** |
| `11` | open lid with ring closed; also closes an open ring | **Verified** |
| `13` | open ring (the lid opens too) | **Verified** |
| `0f` | small flush | **Verified** |
| `0e` | large flush | App-derived |
| `19` | apply settings | **Verified** for automatic lid opening; App-derived for the other fields |

Verified vectors, from E2 `4a52b345090000` and FA `4a52b345113229 33`:

```text
open lid    f3f40f9221114a52b3300010000000000062fc
close lid   f3f40f9221104a52b3300010000000000061fc
open ring   f3f40f9221134a52b3300010000000000064fc
close ring  f3f40f9221114a52b3300010000000000062fc
small flush f3f40f92210f4a52b3300010000000000060fc
auto lid off f3f40f9221194252b3300010000000000062fc
auto lid on  f3f40f9221194a52b330001000000000006afc
```

Front-wash pressure and nozzle share the rear slots in this frame. Gesture, night light,
power save and front-wash values are therefore read-only in this project.

### Option frame (10 bytes): `F3 F4 06 92 21 1F SUB VAL CS FC` **App-derived**

| Setting | SUB | On | Off | Read-back |
| --- | --- | --- | --- | --- |
| UV water disinfection | `21` | `40` | `20` | FA p5 bit 5 |
| Close lid before flush | `25` | `01` | `02` | FA p4 bit 1 |
| Automatic small flush | `25` | `04` | `08` | FA p7 bit 4 |
| Foot sensor | `24` | `01` | `02` | FA p7 bit 5 |
| Ambient light | `33` | `20` | `10` | FA p5 bit 4 |

Not implemented on purpose:
- washing, drying and nozzle cleaning;
- automatic deodorisation and seasonal temperature, whose official encoding reuses
  wash opcodes;
- foam, firmware update, factory reset.

## Optional persistent acquisition

A read-only 90-second observation on the exact ZS800J model showed passive FA flush
on/off, EA movement and later FA changes after the initial query, without polling.
This establishes that notifications can carry changes; it does not establish the meaning
of FA payload[5] bit0. That bit remains Unknown, not refill/water-level/refill-complete.
The opt-in implementation and its separate synthetic/live acceptance boundaries are
documented in [status-stream.md](status-stream.md).

## Known gaps

- There is no transaction id. A query clears the collected frames and waits for a fresh
  E2 / EA / E9 / FA burst, but a very delayed notification cannot be told apart.
- Only one ZS800J unit and one settings profile have been exercised on hardware.
