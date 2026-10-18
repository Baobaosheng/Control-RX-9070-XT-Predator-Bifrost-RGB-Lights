"""Linux I2C transport for the Predator BiFrost lighting MCU.

Talks to `/dev/i2c-N` through the i2c-dev ioctls directly, so there is no dependency
on smbus2 and the exact shape of each transaction is under our control: a plain write
for register writes, and a write-then-read for register reads.

Safety: buses named in `FORBIDDEN_BUS_NAMES` can never be opened, and `--dry-run` callers
never reach here.
"""

from __future__ import annotations

import ctypes
import fcntl
import os
from dataclasses import dataclass
from pathlib import Path

I2C_SLAVE = 0x0703
I2C_RDWR = 0x0707
I2C_M_RD = 0x0001

#: The dGPU's SMU buses reach the GPU power controller. Never open these.
FORBIDDEN_BUS_NAMES = ("AMDGPU SMU",)

#: amdgpu exposes the VBIOS OEM I2C line under this name; the lighting MCU sits on it.
OEM_BUS_NAME = "AMDGPU DM i2c OEM bus"

#: PCI vendor:device of the Navi 48 on the Predator BiFrost RX 9070 XT.
NAVI48_PCI_ID = "1002:7550"

SYSFS_I2C = Path("/sys/bus/i2c/devices")


class _I2cMsg(ctypes.Structure):
    _fields_ = [
        ("addr", ctypes.c_uint16),
        ("flags", ctypes.c_uint16),
        ("len", ctypes.c_uint16),
        ("buf", ctypes.POINTER(ctypes.c_uint8)),
    ]


class _I2cRdwrData(ctypes.Structure):
    _fields_ = [
        ("msgs", ctypes.POINTER(_I2cMsg)),
        ("nmsgs", ctypes.c_uint32),
    ]


@dataclass(frozen=True)
class Adapter:
    number: int
    name: str
    pci: str | None

    @property
    def device(self) -> str:
        return f"/dev/i2c-{self.number}"

    def __str__(self) -> str:
        return f"i2c-{self.number} ({self.name}" + (f", {self.pci})" if self.pci else ")")


def _pci_of(adapter_dir: Path) -> str | None:
    """Walk up the sysfs device chain to the owning PCI function."""
    try:
        real = adapter_dir.resolve()
    except OSError:
        return None
    for part in reversed(real.parts):
        # PCI addresses look like 0000:03:00.0
        if part.count(":") == 2 and "." in part:
            return part
    return None


def list_adapters() -> list[Adapter]:
    adapters = []
    for entry in sorted(SYSFS_I2C.glob("i2c-*"), key=lambda p: int(p.name.split("-")[1])):
        name_file = entry / "name"
        if not name_file.exists():
            continue
        adapters.append(
            Adapter(
                number=int(entry.name.split("-")[1]),
                name=name_file.read_text().strip(),
                pci=_pci_of(entry),
            )
        )
    return adapters


def gpu_pci_addresses() -> set[str]:
    """PCI addresses of every Navi 48 in the machine, from sysfs."""
    found = set()
    for dev in Path("/sys/bus/pci/devices").glob("*"):
        try:
            vendor = (dev / "vendor").read_text().strip()[2:]
            device = (dev / "device").read_text().strip()[2:]
        except OSError:
            continue
        if f"{vendor}:{device}" == NAVI48_PCI_ID:
            found.add(dev.name)
    return found


def find_oem_bus() -> Adapter:
    """The OEM I2C bus belonging to the Predator BiFrost's GPU."""
    adapters = list_adapters()
    gpus = gpu_pci_addresses()

    candidates = [a for a in adapters if a.name == OEM_BUS_NAME]
    if gpus:
        on_gpu = [a for a in candidates if a.pci in gpus]
        if on_gpu:
            candidates = on_gpu

    if not candidates:
        raise RuntimeError(
            f"no {OEM_BUS_NAME!r} adapter found. Available:\n  "
            + "\n  ".join(str(a) for a in adapters)
            + "\nThe OEM bus needs a kernel with amdgpu OEM i2c support; "
            "pass --bus to override."
        )
    if len(candidates) > 1:
        raise RuntimeError(
            "several OEM buses match; pass --bus to choose:\n  "
            + "\n  ".join(str(a) for a in candidates)
        )
    return candidates[0]


def _check_allowed(number: int) -> None:
    for adapter in list_adapters():
        if adapter.number != number:
            continue
        for forbidden in FORBIDDEN_BUS_NAMES:
            if adapter.name.startswith(forbidden):
                raise PermissionError(
                    f"refusing to open {adapter}: writing to the GPU SMU bus is unsafe "
                    "(CLAUDE.md rule 2)"
                )
        return


class I2cBus:
    """A `/dev/i2c-N` handle scoped to one slave address."""

    def __init__(self, number: int, address: int):
        _check_allowed(number)
        self.number = number
        self.address = address
        self._fd: int | None = None

    def __enter__(self) -> I2cBus:
        path = f"/dev/i2c-{self.number}"
        try:
            self._fd = os.open(path, os.O_RDWR)
        except PermissionError as e:
            raise PermissionError(
                f"{path}: permission denied. Add yourself to the 'i2c' group "
                "(`sudo usermod -aG i2c $USER`, then log out and back in)."
            ) from e
        fcntl.ioctl(self._fd, I2C_SLAVE, self.address)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    @property
    def fd(self) -> int:
        if self._fd is None:
            raise RuntimeError("bus is not open; use `with I2cBus(...) as bus:`")
        return self._fd

    def write(self, frame: bytes) -> None:
        """One write transaction: S addr+W <frame> P."""
        os.write(self.fd, frame)

    def read_register_split(self, offset: int, length: int) -> bytes:
        """Write the offset, STOP, then read in a separate transaction.

        This is the framing the lighting MCU is known to answer reliably.
        """
        os.write(self.fd, bytes((offset,)))
        return os.read(self.fd, length)

    def read_register(self, offset: int, length: int) -> bytes:
        """S addr+W <offset> S addr+R <length bytes> P, as one combined transaction."""
        out = (ctypes.c_uint8 * 1)(offset)
        buf = (ctypes.c_uint8 * length)()
        msgs = (_I2cMsg * 2)(
            _I2cMsg(self.address, 0, 1, out),
            _I2cMsg(self.address, I2C_M_RD, length, buf),
        )
        data = _I2cRdwrData(msgs, 2)
        fcntl.ioctl(self.fd, I2C_RDWR, data)
        return bytes(buf)
