"""Validation for uploaded agent avatars and their editor configuration.

The avatar editor renders a square PNG in the browser and sends it together
with the options that produced it.  The server never decodes the image: it only
checks the container shape (signature, IHDR, trailer) and the declared size,
and it validates the shape of the configuration without importing the avatar
library that interprets it.
"""

from __future__ import annotations

import json
import re
import struct
import zlib

from fastapi import status

from auth.errors import AuthError

AVATAR_CONTENT_TYPE = "image/png"
MAX_AVATAR_BYTES = 256 * 1024
MAX_AVATAR_DIMENSION = 512
MAX_AVATAR_CONFIG_BYTES = 1024

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_IEND_CHUNK = b"\x00\x00\x00\x00IEND\xaeB`\x82"
_IHDR_LENGTH = 13
# Signature (8) + length (4) + type (4) + IHDR data (13) + CRC (4).
_MINIMUM_PNG_BYTES = 8 + 4 + 4 + _IHDR_LENGTH + 4 + len(_PNG_IEND_CHUNK)

_VARIANT_PATTERN = re.compile(r"^variant(\d{2})$")
_COLOR_PATTERN = re.compile(r"^#[0-9a-f]{6}$")

# Number of variants the editor offers per part (variant01 through variantNN).
_VARIANT_COUNTS = {
    "eyes": 5,
    "brows": 13,
    "nose": 20,
    "lips": 30,
    "hair": 63,
    "body": 25,
    "glasses": 11,
    "beard": 12,
}
# The editor omits glasses and beard when they are switched off.
_OPTIONAL_KEYS = frozenset({"glasses", "beard"})
_REQUIRED_VARIANT_KEYS = frozenset(_VARIANT_COUNTS) - _OPTIONAL_KEYS
_COLOR_KEYS = frozenset({"backgroundColor"})
_BOOLEAN_KEYS = frozenset({"flip"})
AVATAR_CONFIG_KEYS = frozenset(_VARIANT_COUNTS) | _COLOR_KEYS | _BOOLEAN_KEYS


class AvatarRejected(AuthError):
    """Safe validation failure for an avatar upload."""

    def __init__(
        self,
        *,
        reason: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
    ) -> None:
        super().__init__(
            code="invalid_request",
            message="The request could not be processed.",
            status_code=status_code,
            event="request",
            reason=reason,
        )


def validate_avatar_png(content_type: str | None, data: bytes) -> None:
    """Accept only a small, square PNG container."""

    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type != AVATAR_CONTENT_TYPE:
        raise AvatarRejected(
            reason="avatar_type_unsupported",
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )
    if len(data) > MAX_AVATAR_BYTES:
        raise AvatarRejected(
            reason="avatar_too_large",
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        )
    if len(data) < _MINIMUM_PNG_BYTES or not data.startswith(_PNG_SIGNATURE):
        raise AvatarRejected(reason="avatar_not_png")

    length, chunk_type = struct.unpack(">I4s", data[8:16])
    if length != _IHDR_LENGTH or chunk_type != b"IHDR":
        raise AvatarRejected(reason="avatar_not_png")
    header = data[16 : 16 + _IHDR_LENGTH]
    (declared_crc,) = struct.unpack(">I", data[29:33])
    if zlib.crc32(chunk_type + header) != declared_crc:
        raise AvatarRejected(reason="avatar_not_png")
    if not data.endswith(_PNG_IEND_CHUNK):
        raise AvatarRejected(reason="avatar_not_png")

    width, height = struct.unpack(">II", header[:8])
    if width != height:
        raise AvatarRejected(reason="avatar_not_square")
    if not 1 <= width <= MAX_AVATAR_DIMENSION:
        raise AvatarRejected(reason="avatar_dimensions_invalid")


def parse_avatar_config(raw: str | None) -> dict[str, str | bool] | None:
    """Parse the optional editor configuration against a strict allowlist."""

    if raw is None or raw == "":
        return None
    if len(raw.encode("utf-8")) > MAX_AVATAR_CONFIG_BYTES:
        raise AvatarRejected(reason="avatar_config_too_large")
    try:
        parsed = json.loads(raw)
    except ValueError as error:
        raise AvatarRejected(reason="avatar_config_invalid") from error
    if not isinstance(parsed, dict):
        raise AvatarRejected(reason="avatar_config_invalid")

    config: dict[str, str | bool] = {}
    for key, value in parsed.items():
        valid = False
        if key in _VARIANT_COUNTS:
            match = (
                _VARIANT_PATTERN.fullmatch(value) if isinstance(value, str) else None
            )
            valid = match is not None and 1 <= int(match[1]) <= _VARIANT_COUNTS[key]
        elif key in _COLOR_KEYS:
            valid = isinstance(value, str) and bool(_COLOR_PATTERN.fullmatch(value))
        elif key in _BOOLEAN_KEYS:
            valid = isinstance(value, bool)
        if not valid:
            raise AvatarRejected(reason="avatar_config_invalid")
        config[key] = value
    if not _REQUIRED_VARIANT_KEYS <= config.keys():
        raise AvatarRejected(reason="avatar_config_invalid")
    return config
