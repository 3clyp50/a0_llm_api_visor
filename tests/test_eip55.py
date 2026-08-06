"""Known-answer tests for the vendored EIP-55 checksum helper.

Run standalone (no Agent Zero framework required):

    python -m pytest tests/test_eip55.py -v
    python tests/test_eip55.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(module_name: str, relative_path: str):
    """Load a plugin module directly from disk, bypassing package imports."""
    spec = importlib.util.spec_from_file_location(
        module_name, REPO_ROOT / relative_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {relative_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


eip55 = _load("visor_eip55", "helpers/eip55.py")


class KeccakTest(unittest.TestCase):
    """Keccak-256 must match the original Keccak, not finalised SHA3-256."""

    def test_empty_input_matches_keccak256_not_sha3(self):
        # Keccak-256("") — differs from hashlib.sha3_256(b"").hexdigest()
        self.assertEqual(
            eip55.keccak256(b""),
            "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470",
        )

    def test_abc_vector(self):
        self.assertEqual(
            eip55.keccak256(b"abc"),
            "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45",
        )

    def test_differs_from_stdlib_sha3(self):
        import hashlib

        self.assertNotEqual(
            eip55.keccak256(b""), hashlib.sha3_256(b"").hexdigest()
        )

    def test_input_longer_than_rate(self):
        # 200 bytes > 136-byte rate, exercises two-block absorption.
        # Expected digests cross-checked against OpenSSL's native KECCAK-256:
        #   printf 'x%.0s' $(seq 1 200) | openssl dgst -keccak-256
        self.assertEqual(
            eip55.keccak256(b"x" * 200),
            "3c3800defb6a25a70a2737e0716eeb5d270559ad3cad8f6abddac58802d7158e",
        )

    def test_input_spanning_three_blocks(self):
        # 300 bytes > 2 x 136-byte rate, exercises three-block absorption.
        #   printf 'y%.0s' $(seq 1 300) | openssl dgst -keccak-256
        self.assertEqual(
            eip55.keccak256(b"y" * 300),
            "49cc4a66b35d20d77a48642a8bb66f5d8b5f314eb710b8768a8827d2d206a17f",
        )


class ChecksumTest(unittest.TestCase):
    """Official test vectors from the EIP-55 specification."""

    VECTORS = [
        # all caps
        "0x52908400098527886E0F7030069857D2E4169EE7",
        "0x8617E340B3D01FA5F11F306F4090FD50E238070D",
        # all lower
        "0xde709f2102306220921060314715629080e2fb77",
        "0x27b1fdb04752bbc536007a920d24acb045561c26",
        # normal
        "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
        "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
        "0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB",
        "0xD1220A0cf47c7B9Be7A2E6BA89F429762e7b9aDb",
    ]

    def test_official_vectors_roundtrip(self):
        for expected in self.VECTORS:
            with self.subTest(address=expected):
                self.assertEqual(
                    eip55.to_checksum_address(expected.lower()), expected
                )

    def test_already_checksummed_is_idempotent(self):
        for expected in self.VECTORS:
            with self.subTest(address=expected):
                self.assertEqual(
                    eip55.to_checksum_address(expected), expected
                )

    def test_uppercase_input_is_normalised(self):
        self.assertEqual(
            eip55.to_checksum_address(
                "0X5AAEB6053F3E94C9B9A09F33669435E7EF1BEAED"
            ),
            "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
        )

    def test_surrounding_whitespace_is_tolerated(self):
        self.assertEqual(
            eip55.to_checksum_address(
                "  0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed  "
            ),
            "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
        )

    def test_invalid_addresses_return_empty_string(self):
        for bad in (
            "",
            "   ",
            "0x",
            "not-an-address",
            "5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",  # missing 0x
            "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAe",  # 39 chars
            "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAedd",  # 41 chars
            "0xZZAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",  # non-hex
        ):
            with self.subTest(address=bad):
                self.assertEqual(eip55.to_checksum_address(bad), "")


class RegressionTest(unittest.TestCase):
    """Guards the reported bug: lowercase input must not survive unchanged.

    The upstream Agent Zero API keys stake/quota records by the exact EIP-55
    string, so a lowercase address returns HTTP 200 with all-zero values and
    the sidebar silently renders 0.00 $.
    """

    LOWER = "0x142fa07048997cbf7de37fe5449687f852c18c81"
    CHECKSUMMED = "0x142FA07048997cBF7De37FE5449687f852c18C81"

    def test_reported_address_is_checksummed(self):
        self.assertEqual(eip55.to_checksum_address(self.LOWER), self.CHECKSUMMED)

    def test_lowercase_does_not_pass_through_unchanged(self):
        self.assertNotEqual(eip55.to_checksum_address(self.LOWER), self.LOWER)


if __name__ == "__main__":
    unittest.main(verbosity=2)
