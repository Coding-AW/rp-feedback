# Register map

All offsets are 32-bit words relative to the listed base address. Detailed bit
semantics remain documented in the corresponding HDL headers.

## Feedback path — `0x40300000`

| Offset | Register | Access | Purpose |
|---:|---|:---:|---|
| `0x00` | CI | RW | Gain × cosine, signed Q2.14 |
| `0x04` | CQ | RW | Gain × sine, signed Q2.14 |
| `0x08` | DLY | RW | Integer delay, 1–1022 samples |
| `0x0C` | DELTA | RW | Fractional delay, unsigned Q0.14 |
| `0x10` | BYP | RW | Bypass feedback processing |
| `0x14` | STAT | RO | Invalid-delay clamp status |
| `0x18` | OUT2_MONITOR | RW/RO | Source `[1:0]`, shift `[5:3]`, sticky clip `[8]` |

## Coefficient sequencer - `0x40700000`

| Offset | Register | Access | Purpose |
|---:|---|:---:|---|
| `0x00` | CONTROL | RW | Bit 2 selects sequencer coefficients; write zero for direct CI/CQ |
| `0x0C` | VERSION | RO | Interface version (`5E900001`) |

## Digital resonator — `0x40400000`

| Offset | Register | Access | Purpose |
|---:|---|:---:|---|
| `0x00` | CTRL | RW | Enable and clear state |
| `0x04` | COEF_C | RW | Resonator cosine coefficient |
| `0x08` | COEF_S | RW | Resonator sine coefficient |
| `0x0C` | DELAY | RW | Additional loop delay |
| `0x10` | OUT_SHIFT | RW | Output scaling |
| `0x14` | STATUS | RO | Sticky clipping flag |
| `0x18` | PEEK_U | RO | Current in-phase state |
| `0x1C` | PEEK_V | RO | Current quadrature state |

## Acquisition — `0x40600000`

| Offset | Register | Access | Purpose |
|---:|---|:---:|---|
| `0x00` | CTRL | RW | Enable, reset, test, arm, wrap, port selection |
| `0x04` | LO_FINC | RW | 32-bit DDS frequency increment |
| `0x08` | DEC_LOG2 | RW | Decimation exponent, 6–12 |
| `0x0C` | SRC_SEL | RW | Select IN1 or IN2 |
| `0x10` | TAP_SEL | RW | Mixer, decimator, or corrector scope tap |
| `0x14` | TAP_SHIFT | RW | Select a 14-bit diagnostic window |
| `0x18` | PEEK_I | RO | Most recent I sample |
| `0x1C` | PEEK_Q | RO | Most recent Q sample |
| `0x20` | SAMPLE_CNT | RO | Samples produced since reset |
| `0x24` | STATUS | RO | Primary state flags |
| `0x28` | MEM_START | RW | First DDR byte address |
| `0x2C` | MEM_STOP | RW | Last DDR byte address, inclusive |
| `0x30` | MEM_CUR | RO | Current writer address |
| `0x34` | DMA_COUNT | RO | Samples written since clear |
| `0x38` | STATUS2 | RO | Overflow, filter overrun, and write-error flags |
| `0x40` | COEF_ADDR | RW | FIR coefficient index |
| `0x44` | COEF_DATA | RW | FIR coefficient read/write port |
| `0x48` | BUILD_ID | RO | Qualified hardware-interface ID, fixed at `FE76AE09` |

Use AXI port 0 for acquisition. Port 1 remains diagnostic-only on the current
board because its processor-side configuration drops half of each 64-bit sample.
