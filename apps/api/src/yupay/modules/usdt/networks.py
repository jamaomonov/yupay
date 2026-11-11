"""The chains USDT top-up accepts, and what is fixed about each (ADR-0104).

A row in ``usdt_networks`` holds what an admin sets (address, on/off) and the
poll cursor; everything here is a fact about the chain and its USDT contract
and is not configurable on purpose — a wrong contract address would credit a
fake token.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

NetworkCode = Literal["trc20", "bep20", "erc20"]
Kind = Literal["tron", "evm"]


@dataclass(frozen=True)
class Network:
    """One chain's USDT.

    Attributes:
        code: Stored in the database and on the wire.
        kind: Which reader polls it.
        contract: Tether's USDT contract on this chain. Nothing else is money.
        decimals: The contract's decimals (18 on BNB Chain, 6 elsewhere).
        confirmations: Blocks a transfer must be buried under before it is
            read (EVM only; TronGrid's ``only_confirmed`` covers TRON).
        max_blocks: The widest ``eth_getLogs`` range asked for at once.
    """

    code: NetworkCode
    kind: Kind
    contract: str
    decimals: int
    confirmations: int = 0
    max_blocks: int = 0
    #: ``eth_chainId`` the node must report (EVM only): a misconfigured URL
    #: pointing at another chain is refused rather than read.
    chain_id: int = 0


TRC20: Final = Network("trc20", "tron", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", 6)
#: ~0.75 s blocks: 20 confirmations is ~15 s, well past BNB Chain's fast finality.
BEP20: Final = Network(
    "bep20",
    "evm",
    "0x55d398326f99059fF775485246999027B3197955",
    18,
    confirmations=20,
    max_blocks=1000,
    chain_id=56,
)
#: ~12 s blocks: 12 confirmations is ~2.5 min.
ERC20: Final = Network(
    "erc20",
    "evm",
    "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    6,
    confirmations=12,
    max_blocks=500,
    chain_id=1,
)

NETWORKS: Final[dict[str, Network]] = {n.code: n for n in (TRC20, BEP20, ERC20)}
CODES: Final = tuple(NETWORKS)


__all__ = ["BEP20", "CODES", "ERC20", "NETWORKS", "TRC20", "Kind", "Network", "NetworkCode"]
