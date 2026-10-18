"""Frame encoding for the BiFrost lighting MCU at 0x68 (HID LampArray reports over registers).

Pure functions and tables, no I/O — everything here is testable without hardware. See
docs/REGISTERS.md for the register map. A "transaction" here is the byte string written to the
device: register number first, then payload.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# --- transport constants (docs/REGISTERS.md) --------------------------------------

I2C_ADDRESS = 0x68  # 7-bit, on the GPU's "AMDGPU DM i2c OEM bus"
BUS_SPEED_KHZ = 100
MAX_TRANSFER = 12  # largest payload sent in one write

# --- registers (docs/REGISTERS.md) ------------------------------------------------
# 0x04-0x06 carry the payload of the HID LampArray report with the same ID.

REG_LAMP_MULTI_UPDATE = 0x04
REG_LAMP_RANGE_UPDATE = 0x05
REG_AUTO_MODE = 0x06
REG_LAMP_COUNT = 0x10
REG_LAMP_ATTRIBUTES = 0x11
REG_CHALLENGE = 0x12
REG_RESPONSE = 0x13

#: The only registers this module will encode a write for.
WRITE_REGISTERS = frozenset(
    {REG_LAMP_MULTI_UPDATE, REG_LAMP_RANGE_UPDATE, REG_AUTO_MODE, REG_LAMP_ATTRIBUTES, REG_CHALLENGE}
)
#: The registers that may be read.
READ_REGISTERS = frozenset({REG_LAMP_COUNT, REG_LAMP_ATTRIBUTES, REG_RESPONSE})

MAX_LAMPS = 6  # logo segments on the RX 9070 XT, reported by 0x10
LAMPS_PER_MULTI_CHUNK = 2  # 1 flag byte + 2 x 5-byte entries fits MAX_TRANSFER
LAMP_UPDATE_COMPLETE = 0x01  # HID LampUpdateFlags bit 0
HANDSHAKE_DELAY_S = 0.010  # wait between writing 0x12 and reading 0x13

CRC_POLY = 0x04C11DB7
CRC_INIT = 0xFFFFFFFF


class EncodeError(ValueError):
    """A request the protocol cannot express, or that falls outside the whitelist."""


def transaction(reg: int, payload: bytes) -> bytes:
    """One register write, as sent on the wire after the address byte."""
    if reg not in WRITE_REGISTERS:
        raise EncodeError(f"register 0x{reg:02x} is not a writable register")
    if not 1 <= len(payload) <= MAX_TRANSFER:
        raise EncodeError(f"payload of {len(payload)} bytes; allowed 1..{MAX_TRANSFER}")
    return bytes((reg,)) + payload


def _byte(name: str, value: int) -> int:
    if not 0 <= value <= 0xFF:
        raise EncodeError(f"{name} out of range: {value}")
    return value


# --- identity check (docs/REGISTERS.md) -------------------------------------------


def crc32_ite(data: bytes) -> int:
    """Challenge CRC: MSB-first register, input bits taken LSB-first, no final XOR."""
    crc = CRC_INIT
    for byte in data:
        for i in range(8):
            msb = crc >> 31
            crc = (crc << 1) & 0xFFFFFFFF
            if msb != (byte >> i) & 1:
                crc ^= CRC_POLY
    return crc


def challenge_bytes(value: int) -> bytes:
    """The 4 bytes written to 0x12 for a 32-bit challenge, little-endian."""
    return (value & 0xFFFFFFFF).to_bytes(4, "little")


def challenge_frame(value: int) -> bytes:
    return transaction(REG_CHALLENGE, challenge_bytes(value))


def response_matches(challenge: int, response: bytes) -> bool:
    """True if the 4 bytes read from 0x13 answer `challenge`."""
    if len(response) != 4:
        raise EncodeError(f"response must be 4 bytes, got {len(response)}")
    return int.from_bytes(response, "little") == crc32_ite(challenge_bytes(challenge))


# --- lamp discovery -----------------------------------------------------------------


def attribute_query_frames(lamp_count: int) -> list[tuple[bytes, int]]:
    """(write, read length) pairs for 0x11, at most 6 lamps per chunk: 2 bytes per lamp."""
    if not 0 <= lamp_count <= 0xFF:
        raise EncodeError(f"lamp count out of range: {lamp_count}")
    out, start, left = [], 0, lamp_count
    while left > 0:
        n = min(left, MAX_LAMPS)
        out.append((transaction(REG_LAMP_ATTRIBUTES, bytes((2 * start, 2 * n))), 2 * n))
        start, left = start + n, left - n
    return out


# --- colour and mode ----------------------------------------------------------------


@dataclass(frozen=True)
class LampColor:
    lamp_id: int
    red: int
    green: int
    blue: int
    intensity: int = 0xFF

    def entry(self) -> bytes:
        return bytes(
            _byte(n, v)
            for n, v in (
                ("lamp_id", self.lamp_id),
                ("red", self.red),
                ("green", self.green),
                ("blue", self.blue),
                ("intensity", self.intensity),
            )
        )


def auto_mode_frame(autonomous: bool) -> bytes:
    """0x06: 1 hands the lamps to the MCU's own effect, 0 means the host drives them."""
    return transaction(REG_AUTO_MODE, b"\x01" if autonomous else b"\x00")


def range_update_frame(
    start: int, end: int, red: int, green: int, blue: int, intensity: int = 0xFF,
    flags: int = LAMP_UPDATE_COMPLETE,
) -> bytes:
    """0x05: the 9-byte LampRangeUpdate payload — flags, start/end (LE16), R, G, B, I."""
    if not 0 <= start <= end <= 0xFFFF:
        raise EncodeError(f"bad lamp range {start}..{end}")
    payload = bytes((_byte("flags", flags),))
    payload += start.to_bytes(2, "little") + end.to_bytes(2, "little")
    payload += bytes(_byte(n, v) for n, v in (("red", red), ("green", green), ("blue", blue), ("intensity", intensity)))
    return transaction(REG_LAMP_RANGE_UPDATE, payload)


def multi_update_frames(lamps: Sequence[LampColor]) -> list[bytes]:
    """0x04: per-lamp colours, 2 lamps per write; byte 0 is 1 on the chunk with the last lamps."""
    if not lamps:
        raise EncodeError("no lamps")
    frames, left = [], len(lamps)
    for i in range(0, len(lamps), LAMPS_PER_MULTI_CHUNK):
        chunk = lamps[i : i + LAMPS_PER_MULTI_CHUNK]
        last = 1 if left <= LAMPS_PER_MULTI_CHUNK else 0
        frames.append(transaction(REG_LAMP_MULTI_UPDATE, bytes((last,)) + b"".join(l.entry() for l in chunk)))
        left -= len(chunk)
    return frames


def all_lamps(lamp_count: int, red: int, green: int, blue: int, intensity: int = 0xFF) -> list[LampColor]:
    return [LampColor(i, red, green, blue, intensity) for i in range(lamp_count)]


def hexdump(frames: Iterable[bytes]) -> str:
    return "\n".join(" ".join(f"{b:02x}" for b in f) for f in frames)
