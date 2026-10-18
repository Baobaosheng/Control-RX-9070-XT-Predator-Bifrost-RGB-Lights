"""Tests for the register encoder. Expected bytes follow docs/REGISTERS.md."""

from __future__ import annotations

import pytest

from acer_bifrost_rgb import ite


def _reverse_bits(b: int) -> int:
    return int(f"{b:08b}"[::-1], 2)


def _crc32_mpeg2(data: bytes) -> int:
    """Reference CRC-32/MPEG-2 (MSB-first, init 0xffffffff, no final XOR), written independently."""
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    return crc


def test_reference_crc_check_value():
    assert _crc32_mpeg2(b"123456789") == 0x0376E6E7


@pytest.mark.parametrize("data", [b"", b"\x00", b"\xff", b"123456789", bytes(range(4)), b"\xde\xad\xbe\xef"])
def test_ite_crc_is_mpeg2_over_bit_reversed_bytes(data):
    # Each byte is fed LSB-first into an MSB-first register.
    assert ite.crc32_ite(data) == _crc32_mpeg2(bytes(_reverse_bits(b) for b in data))


def test_crc_of_empty_is_init():
    assert ite.crc32_ite(b"") == 0xFFFFFFFF


def test_challenge_frame_is_little_endian():
    assert ite.challenge_frame(0x11223344) == bytes([0x12, 0x44, 0x33, 0x22, 0x11])


def test_response_matches_round_trip():
    value = 0xCAFEF00D
    expected = ite.crc32_ite(ite.challenge_bytes(value)).to_bytes(4, "little")
    assert ite.response_matches(value, expected)
    assert not ite.response_matches(value, bytes(4) if expected != bytes(4) else b"\x01\x00\x00\x00")


def test_response_length_checked():
    with pytest.raises(ite.EncodeError):
        ite.response_matches(0, b"\x00\x00\x00")


def test_auto_mode_frames_match_check_device():
    # ITEAMD_CheckDevice.exe /am1 and /am0
    assert ite.auto_mode_frame(True) == b"\x06\x01"
    assert ite.auto_mode_frame(False) == b"\x06\x00"


def test_range_update_layout():
    frame = ite.range_update_frame(0, 5, 0xFF, 0x00, 0x00)
    assert frame == bytes([0x05, 0x01, 0x00, 0x00, 0x05, 0x00, 0xFF, 0x00, 0x00, 0xFF])
    assert len(frame) - 1 == 9  # HID report 5 is 9 bytes after its ID


def test_range_update_rejects_inverted_range():
    with pytest.raises(ite.EncodeError):
        ite.range_update_frame(3, 2, 0, 0, 0)


def test_multi_update_chunks_and_last_flag():
    lamps = ite.all_lamps(5, 1, 2, 3, 4)
    frames = ite.multi_update_frames(lamps)
    assert [f[1] for f in frames] == [0, 0, 1]
    assert frames[0] == bytes([0x04, 0x00, 0, 1, 2, 3, 4, 1, 1, 2, 3, 4])
    assert frames[-1] == bytes([0x04, 0x01, 4, 1, 2, 3, 4])
    assert all(len(f) - 1 <= ite.MAX_TRANSFER for f in frames)


def test_multi_update_two_lamps_is_one_last_chunk():
    frames = ite.multi_update_frames(ite.all_lamps(2, 9, 9, 9))
    assert len(frames) == 1 and frames[0][1] == 1


def test_attribute_query_matches_app_chunking():
    assert ite.attribute_query_frames(6) == [(bytes([0x11, 0x00, 0x0C]), 12)]
    assert ite.attribute_query_frames(8) == [
        (bytes([0x11, 0x00, 0x0C]), 12),
        (bytes([0x11, 0x0C, 0x04]), 4),
    ]
    assert ite.attribute_query_frames(0) == []


def test_whitelist_refuses_other_registers():
    for reg in (0x00, 0x03, 0x07, 0x10, 0x13, 0x2E, 0x20, 0x25):
        with pytest.raises(ite.EncodeError):
            ite.transaction(reg, b"\x00")


def test_payload_length_bounds():
    with pytest.raises(ite.EncodeError):
        ite.transaction(ite.REG_AUTO_MODE, b"")
    with pytest.raises(ite.EncodeError):
        ite.transaction(ite.REG_LAMP_MULTI_UPDATE, bytes(13))


def test_byte_range_checked():
    with pytest.raises(ite.EncodeError):
        ite.LampColor(0, 256, 0, 0).entry()
