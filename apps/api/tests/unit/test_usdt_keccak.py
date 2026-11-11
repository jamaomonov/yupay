"""Keccak-256 and EIP-55 against published vectors: the admin's address check rests on them."""

from __future__ import annotations

import pytest
from yupay.modules.usdt.address import evm_checksum, is_evm_address
from yupay.modules.usdt.evm import TRANSFER_TOPIC
from yupay.modules.usdt.keccak import keccak256
from yupay.modules.usdt.networks import BEP20, ERC20


@pytest.mark.parametrize(
    ("data", "digest"),
    [
        (b"", "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"),
        (b"abc", "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45"),
        (b"a" * 200, keccak256(b"a" * 136 + b"a" * 64).hex()),  # multi-block absorb
    ],
)
def test_keccak256_vectors(data: bytes, digest: str) -> None:
    assert keccak256(data).hex() == digest


def test_the_transfer_topic_is_keccak_of_the_event_signature() -> None:
    assert "0x" + keccak256(b"Transfer(address,address,uint256)").hex() == TRANSFER_TOPIC


@pytest.mark.parametrize(
    "address",
    [
        # EIP-55's own test vectors, and the USDT contracts themselves.
        "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
        "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
        "0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB",
        "0xD1220A0cf47c7B9Be7A2E6BA89F429762e7b9aDb",
        BEP20.contract,
        ERC20.contract,
    ],
)
def test_eip55_accepts_checksummed(address: str) -> None:
    assert is_evm_address(address)
    assert evm_checksum(address.lower()) == address


@pytest.mark.parametrize(
    "address",
    [
        "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAeD",  # one letter's case flipped
        "0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed",  # no checksum to check
        "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeA",  # short
        "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
    ],
)
def test_eip55_refuses_typos_and_unchecksummed(address: str) -> None:
    assert not is_evm_address(address)
