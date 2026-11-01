"""Helpers that build minimal valid PNG files for avatar tests."""

from __future__ import annotations

import struct
import zlib


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data))
    )


def make_png(width: int = 256, height: int | None = None, *, pad: int = 0) -> bytes:
    """Return a real RGBA PNG; ``pad`` appends an ancillary chunk to grow it."""

    height = width if height is None else height
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    row = b"\x00" + b"\x10\x20\x30\xff" * width
    pixels = zlib.compress(row * height)
    body = _chunk(b"IHDR", header) + _chunk(b"IDAT", pixels)
    if pad:
        body += _chunk(b"tEXt", b"x\x00" + b"a" * pad)
    return b"\x89PNG\r\n\x1a\n" + body + _chunk(b"IEND", b"")
