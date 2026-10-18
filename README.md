# RX 9070 XT Predator BiFrost — RGB control for Linux

Linux control for the logo lighting of the **Acer Predator BiFrost Radeon RX 9070 XT**: static
colours, per-segment colours and 13 animated effects, with a systemd user service to restore your
setting at login. No root and no kernel module are needed.

The logo has 6 independently addressable segments (the fans have no LEDs). It sits behind a
lighting MCU on the GPU's OEM I2C bus. The register-level protocol is documented in
**[docs/REGISTERS.md](docs/REGISTERS.md)**.

## Requirements

- Linux with amdgpu exposing `AMDGPU DM i2c OEM bus` (kernel ≥ 6.15).
- `i2c-dev` loaded, and your user in the `i2c` group.
- Python ≥ 3.13 and [uv](https://docs.astral.sh/uv/).

```sh
sudo modprobe i2c-dev                      # or add i2c-dev to /etc/modules-load.d/
groups | grep -q i2c || sudo usermod -aG i2c "$USER"   # then log out and back in
uv sync
```

## Usage

Colours are listed **left to right** as seen on the card. Add `--dry-run` to any command to print
the register writes instead of sending them.

```sh
uv run acer-bifrost-rgb info                          # bus, address, lamp count (expect 6)
uv run acer-bifrost-rgb color 00aec7                  # whole logo one colour
uv run acer-bifrost-rgb color ff0000 --brightness 40
uv run acer-bifrost-rgb lamps ff00ff 00ffff ffff00 0000ff 00ff00 ff0000   # one per segment
uv run acer-bifrost-rgb effects                       # list the effects
uv run acer-bifrost-rgb effect rainbow-wave --speed 6 # runs until Ctrl+C
uv run acer-bifrost-rgb effect gradient-wave --colors ff0080 0080ff --fps 25
uv run acer-bifrost-rgb off
```

### Effects

The effects are animated by the host and modelled on the OpenRGB Effects plugin:

- `static`, `breathing`, `spectrum-cycle`, `rainbow-wave`, `gradient-wave`;
- `comet`, `visor`, `marquee`, `fill`;
- `smooth-blink`, `starry-night`, `lightning`, `swap`.

Options: `--colors`, `--speed 1..10`, `--brightness 0..100`, `--fps 1..30` (default 25).

`--speed` accepts decimals:

| speed | multiplier | e.g. `breathing` cycle |
|---|---|---|
| 1 | ×0.33 | ~12 s |
| 5 (default) | ×1 | 4 s |
| 10 | ×4 | 1 s |

### Keep your setting across power-offs

The card forgets its colours when power is removed. Save a setting and let a systemd user service
re-apply it at login:

```sh
uv run acer-bifrost-rgb effect breathing --colors 00aec7 ff0080 --save   # or color/lamps/off --save
uv run acer-bifrost-rgb service --write
systemctl --user daemon-reload && systemctl --user enable --now acer-bifrost-rgb.service
```

The setting lives in `~/.config/acer-bifrost-rgb/config.toml`, including the speed. `uv run
acer-bifrost-rgb apply` re-applies it by hand.

## Safety

- The tool only opens the GPU's OEM bus. It refuses the `AMDGPU SMU` buses, which reach the GPU
  power controller.
- It writes only the colour and mode registers (`0x04`, `0x05`, `0x06`). It checks that `0x10`
  reports 6 lamps before writing, and stops after repeated I/O errors.
- Worst case: wrong colours until the next power cycle. No register written here is persistent.

## OpenRGB

An OpenRGB controller for this card (one "Logo" zone, Direct and Off modes) has been written and
tested against OpenRGB master. It is not merged upstream yet.

## Development

```sh
uv run pytest        # encoder, device, effects, runner, config — no hardware needed
```

## Disclaimer

This is an independent project, not affiliated with or endorsed by Acer or ITE. "Acer",
"Predator" and "BiFrost" are trademarks of their respective owners. Use at your own risk.
