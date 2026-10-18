# BiFrost RX 9070 XT lighting — register reference

The logo of the Acer Predator BiFrost Radeon RX 9070 XT (PCI `1002:7550`, subsystem
`1025:187A`) is driven by an ITE lighting MCU. It is the card's only lit part: 6 segments; the
fans have no LEDs. The MCU accepts HID LampArray-style colour updates as plain I2C register
writes.

Everything below has been checked on the card unless marked *(unverified)*.

## Transport

| | |
|---|---|
| Bus | the GPU's `AMDGPU DM i2c OEM bus` (`i2c-10` on the reference machine; exposed by amdgpu since kernel 6.15) |
| Address | `0x68` (7-bit) |
| Speed | 100 kHz |
| Write | `S 0x68+W <reg> <data…> P`, at most 12 data bytes |
| Read | `S 0x68+W <reg> P`, then `S 0x68+R <n bytes> P` (write the register, STOP, then read) |

No handshake is required before writing colours.

## Registers

| reg | dir | bytes | meaning |
|---|---|---|---|
| `0x04` | W | 1 + 5·n, n ≤ 2 | **per-lamp colour**: `[last, (lamp, R, G, B, I) × n]`; `last = 1` on the write that carries the final lamps |
| `0x05` | W | 9 | **lamp-range colour**: `[flags, first lo, first hi, last lo, last hi, R, G, B, I]`, `flags = 01` (update complete) |
| `0x06` | W | 1 | **mode**: `00` = host control (colours come from `0x04`/`0x05`); `01` = MCU's built-in effect (dark on this card) |
| `0x10` | R | 1 | **lamp count**: `06` |
| `0x11` | W then R | 2 / 2·n | lamp attributes: write `[2·first, 2·n]`, read 2 bytes per lamp. Reads `(0x0a + i, 0x01)` for lamp *i*; the meaning is *(unverified)* |
| `0x12` | W | 4 | identity check: 32-bit challenge, little-endian |
| `0x13` | R | 4 | identity check: response = CRC-32 of the challenge (poly `0x04C11DB7`, init `0xFFFFFFFF`, input bits LSB-first, no final XOR), little-endian; read ≥ 10 ms after writing `0x12` |

`I` (intensity) is written as `FF`; brightness is applied by scaling R, G and B.

## Lamp layout

Lamp 0 is the **rightmost** logo segment and lamp 5 the **leftmost**. `acer-bifrost-rgb` takes
colours left to right and reverses them.

## Typical sequence

```
read  0x10            → 06                       # it is the 6-lamp logo MCU
write 06 00                                      # host control
write 05 01 00 00 05 00 ff 00 00 ff              # whole logo red
write 04 00 00 ff 00 00 ff 01 00 ff 00 ff        # lamps 0–1: red, green
write 04 00 02 00 00 ff ff 03 ff ff 00 ff        # lamps 2–3: blue, yellow
write 04 01 04 00 ff ff ff 05 ff 00 ff ff        # lamps 4–5: cyan, magenta (last)
```

## Behaviour

- **Persistence:** colours survive a warm reboot but are lost when power is removed. After a cold
  boot the logo is dark until a host sends colours again.
- **Rate:** a steady stream of about 75 writes/s (25 fps, 3 writes per frame) ran without errors.
- **Register sweeps:** avoid them. Probing unrelated registers (e.g. with `i2cdump`) is unnecessary
  and can leave the MCU's built-in effect dark.
