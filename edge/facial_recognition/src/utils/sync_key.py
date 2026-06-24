"""Helpers for edge-generated cloud synchronization keys."""

from __future__ import annotations

import secrets
import time


_CROCKFORD_BASE32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode_base32(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_CROCKFORD_BASE32[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def generate_sync_key() -> str:
    """Return a 26-character ULID-compatible key for idempotent cloud sync."""

    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    randomness = secrets.randbits(80)
    return _encode_base32(timestamp_ms, 10) + _encode_base32(randomness, 16)
