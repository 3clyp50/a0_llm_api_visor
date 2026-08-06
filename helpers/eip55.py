"""Minimal EIP-55 address checksumming, dependency-free.

The Agent Zero API keys stake and quota records by the exact EIP-55
checksummed address string. A lowercase address still resolves on-chain
balances (those are looked up case-insensitively) but misses the stake
lookup, so the API answers HTTP 200 with all-zero quota values and the
visor silently renders ``0.00 $``.

Normalising every address to its checksummed form before calling the API
removes that failure mode entirely.

EIP-55 requires **Keccak-256**, which is the original Keccak submission and
not the finalised SHA3 standard. ``hashlib.sha3_256`` therefore cannot be
used: it applies the ``0x06`` domain-separation byte, whereas Keccak-256
uses ``0x01``, producing different digests for identical input.

The plugin has no third-party dependencies, so a compact Keccak-256 is
vendored here rather than pulling in ``eth-utils`` (which would add
``eth-hash``, ``pycryptodome`` and friends to a plugin that otherwise needs
nothing beyond the standard library).

Reference: https://eips.ethereum.org/EIPS/eip-55
"""

from __future__ import annotations

import re

__all__ = ["keccak256", "to_checksum_address", "is_address", "ADDRESS_RE"]

ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

_MASK = (1 << 64) - 1
_RATE_BYTES = 136  # 1088-bit rate for Keccak-256
_ROUNDS = 24

_ROUND_CONSTANTS = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A,
    0x8000000080008000, 0x000000000000808B, 0x0000000080000001,
    0x8000000080008081, 0x8000000000008009, 0x000000000000008A,
    0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
    0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
    0x000000000000800A, 0x800000008000000A, 0x8000000080008081,
    0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)

# Rotation offsets, indexed [x][y].
_ROTATION_OFFSETS = (
    (0, 36, 3, 41, 18),
    (1, 44, 10, 45, 2),
    (62, 6, 43, 15, 61),
    (28, 55, 25, 21, 56),
    (27, 20, 39, 8, 14),
)


def _rotl64(value: int, shift: int) -> int:
    """Rotate a 64-bit lane left by ``shift`` bits."""
    return ((value << shift) | (value >> (64 - shift))) & _MASK


def _keccak_f1600(state: list[list[int]]) -> list[list[int]]:
    """Apply the Keccak-f[1600] permutation in place."""
    for round_index in range(_ROUNDS):
        # theta
        column_parity = [
            state[x][0] ^ state[x][1] ^ state[x][2] ^ state[x][3] ^ state[x][4]
            for x in range(5)
        ]
        theta_d = [
            column_parity[(x - 1) % 5] ^ _rotl64(column_parity[(x + 1) % 5], 1)
            for x in range(5)
        ]
        for x in range(5):
            for y in range(5):
                state[x][y] ^= theta_d[x]

        # rho and pi
        permuted = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                permuted[y][(2 * x + 3 * y) % 5] = _rotl64(
                    state[x][y], _ROTATION_OFFSETS[x][y]
                )

        # chi
        for x in range(5):
            for y in range(5):
                state[x][y] = permuted[x][y] ^ (
                    (~permuted[(x + 1) % 5][y]) & _MASK & permuted[(x + 2) % 5][y]
                )

        # iota
        state[0][0] ^= _ROUND_CONSTANTS[round_index]

    return state


def keccak256(data: bytes) -> str:
    """Return the Keccak-256 hex digest of ``data``.

    This is original Keccak (``0x01`` padding), not finalised SHA3
    (``0x06`` padding). The two produce different digests.
    """
    state = [[0] * 5 for _ in range(5)]

    # Pad: 0x01 ... 0x80 (multi-rate padding, Keccak variant).
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % _RATE_BYTES:
        padded.append(0x00)
    padded[-1] ^= 0x80

    # Absorb.
    for offset in range(0, len(padded), _RATE_BYTES):
        block = padded[offset : offset + _RATE_BYTES]
        for lane_index in range(_RATE_BYTES // 8):
            lane = int.from_bytes(
                block[lane_index * 8 : lane_index * 8 + 8], "little"
            )
            state[lane_index % 5][lane_index // 5] ^= lane
        state = _keccak_f1600(state)

    # Squeeze 32 bytes (4 lanes) — no second permutation needed since
    # the output is shorter than the rate.
    digest = b"".join(
        state[i % 5][i // 5].to_bytes(8, "little") for i in range(4)
    )
    return digest.hex()


def is_address(value: str) -> bool:
    """Return ``True`` if ``value`` looks like a 0x-prefixed 20-byte address."""
    return bool(ADDRESS_RE.match((value or "").strip()))


def to_checksum_address(value: str) -> str:
    """Return ``value`` as an EIP-55 checksummed address.

    Accepts any casing, with or without surrounding whitespace. Returns an
    empty string when the input is not a well-formed address, matching the
    plugin's existing "empty means unset" convention.
    """
    candidate = (value or "").strip()
    if not candidate:
        return ""

    # Tolerate an uppercase "0X" prefix before validating.
    if candidate[:2].lower() == "0x":
        candidate = "0x" + candidate[2:]

    if not ADDRESS_RE.match(candidate):
        return ""

    body = candidate[2:].lower()
    digest = keccak256(body.encode("ascii"))

    return "0x" + "".join(
        char.upper() if char.isalpha() and int(digest[index], 16) >= 8 else char
        for index, char in enumerate(body)
    )
