"""The BiFrost logo as a device: colours in, register writes out (docs/REGISTERS.md).

`BifrostDevice` owns one `/dev/i2c-N` handle to the lighting MCU at 0x68 on the GPU's OEM bus.

- Host control (`0x06 = 0`) is sent once, before the first colour.
- Unchanged frames are skipped.
- A uniform frame costs one `0x05` write; otherwise it costs three `0x04` writes.

Colours are given left to right; lamp 0 is the rightmost segment, so the order is reversed here.
`dry_run=True` logs the frames without opening the bus.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from . import bus, ite
from .effects import RGB

Log = Callable[[str], None]


class DeviceError(RuntimeError):
    pass


class BifrostDevice:
    def __init__(self, bus_number: int | None = None, dry_run: bool = False, log: Log | None = None):
        self.dry_run = dry_run
        self.log = log or (lambda _msg: None)
        self.bus_number = bus_number if bus_number is not None else bus.find_oem_bus().number
        self.lamps = ite.MAX_LAMPS
        self._handle: bus.I2cBus | None = None
        self._host_control = False
        self._last: list[RGB] | None = None
        self.writes = 0

    def __enter__(self) -> BifrostDevice:
        if not self.dry_run:
            self._handle = bus.I2cBus(self.bus_number, ite.I2C_ADDRESS).__enter__()
            count = self.read_lamp_count()
            if count != ite.MAX_LAMPS:
                self.close()
                raise DeviceError(
                    f"i2c-{self.bus_number} 0x{ite.I2C_ADDRESS:02x}: lamp count {count}, expected "
                    f"{ite.MAX_LAMPS} — not the BiFrost ITE MCU, refusing to write"
                )
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.__exit__(None, None, None)
            self._handle = None

    def read_lamp_count(self) -> int:
        if self._handle is None:
            return self.lamps
        return self._handle.read_register_split(ite.REG_LAMP_COUNT, 1)[0]

    def _write(self, frame: bytes) -> None:
        self.writes += 1
        self.log("W " + frame.hex(" "))
        if self._handle is not None:
            self._handle.write(frame)

    def take_control(self) -> None:
        if not self._host_control:
            self._write(ite.auto_mode_frame(False))
            self._host_control = True

    def release(self) -> None:
        """Hand the lamps back to the MCU's built-in effect (dark on this card)."""
        self._write(ite.auto_mode_frame(True))
        self._host_control = False
        self._last = None

    def show(self, colors: Sequence[RGB], force: bool = False) -> bool:
        """Display one frame (left to right). Returns False if it was skipped as unchanged."""
        if len(colors) != self.lamps:
            raise ValueError(f"need {self.lamps} colours, got {len(colors)}")
        frame = [tuple(int(v) for v in c) for c in colors]
        if not force and frame == self._last:
            return False
        self.take_control()
        if all(c == frame[0] for c in frame):
            self._write(ite.range_update_frame(0, self.lamps - 1, *frame[0]))
        else:
            lamps = [ite.LampColor(self.lamps - 1 - i, *c) for i, c in enumerate(frame)]
            lamps.sort(key=lambda lamp: lamp.lamp_id)
            for f in ite.multi_update_frames(lamps):
                self._write(f)
        self._last = frame  # type: ignore[assignment]
        return True

    def fill(self, color: RGB) -> bool:
        return self.show([color] * self.lamps)

    def off(self) -> bool:
        return self.fill((0, 0, 0))
