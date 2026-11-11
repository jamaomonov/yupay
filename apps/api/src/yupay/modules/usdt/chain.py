"""What every chain reader returns, so the poll and the intake do not care which chain it was."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


class ChainUnavailableError(Exception):
    """The chain's API did not answer usably; the caller retries on the next tick."""


@dataclass(frozen=True)
class Transfer:
    """One confirmed USDT transfer to our address.

    Attributes:
        network: ``trc20`` / ``bep20`` / ``erc20``.
        tx_id: The transaction hash.
        event_key: Tells apart several transfers in one transaction: the log
            index on EVM chains, sender + raw value on TRON.
        position: Where it sits for the poll cursor: block time in ms on TRON,
            block number on EVM chains.
    """

    network: str
    tx_id: str
    event_key: str
    from_address: str
    to_address: str
    amount: Decimal
    block_at: datetime
    position: int


@dataclass(frozen=True)
class Batch:
    """One read of a chain.

    Attributes:
        transfers: The rows that are ours to count, oldest first.
        last_position: How far the read got — spam rows included — in the
            cursor's unit; ``None`` when nothing came back.
        truncated: The read stopped at its own cap before the chain ran out.
            The caller resumes from ``last_position`` without any overlap.
    """

    transfers: list[Transfer]
    last_position: int | None
    truncated: bool


__all__ = ["Batch", "ChainUnavailableError", "Transfer"]
