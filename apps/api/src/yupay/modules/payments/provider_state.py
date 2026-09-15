"""Admin-controlled provider state: the logical↔slug map, state read/write, and
the customer-facing status resolver.

Single source of truth consumed by ``create_intent`` (block new intents),
``GET /payments/providers`` (hide disabled, flag maintenance), and the admin
endpoints. Webhook paths deliberately do NOT consult this — in-flight payments
must settle regardless of admin state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import NotFoundError
from yupay.modules.payments.gateways import REGISTRY
from yupay.modules.payments.models import PaymentProviderState

ProviderState = Literal["active", "disabled", "maintenance"]
CustomerStatus = Literal["active", "maintenance"]

_VALID_STATES: frozenset[str] = frozenset({"active", "disabled", "maintenance"})


@dataclass(frozen=True)
class LogicalProvider:
    """A provider as an operator thinks of it — may map to >1 registry slug."""

    display_name: str
    slugs: list[str]


# Click spans two surface slugs but is one control. Wallet is in-house but
# rides the same lever so an FX drop (ADR-0056) can stop pay-from-balance too.
LOGICAL_PROVIDERS: dict[str, LogicalProvider] = {
    "click": LogicalProvider("Click", ["click", "click_miniapp"]),
    "payme": LogicalProvider("Payme", ["payme"]),
    "uzum": LogicalProvider("Uzum", ["uzum"]),
    "octo": LogicalProvider("Octo", ["octo"]),
    "paynet": LogicalProvider("Paynet", ["paynet"]),
    "crypto": LogicalProvider("USDT (crypto)", ["crypto"]),
    "wallet": LogicalProvider("Кошелёк", ["wallet"]),
}

SLUG_TO_LOGICAL: dict[str, str] = {
    slug: logical for logical, lp in LOGICAL_PROVIDERS.items() for slug in lp.slugs
}


async def get_states(db: AsyncSession, slugs: list[str]) -> dict[str, ProviderState]:
    """Return the state of each slug, defaulting missing rows to ``active``."""
    rows = (
        await db.execute(
            select(PaymentProviderState).where(PaymentProviderState.provider.in_(slugs))
        )
    ).scalars()
    stored = {r.provider: _coerce(r.state) for r in rows}
    return {slug: stored.get(slug, "active") for slug in slugs}


async def get_state(db: AsyncSession, slug: str) -> ProviderState:
    """State of a single slug (``active`` if no row)."""
    return (await get_states(db, [slug]))[slug]


async def set_logical_state(
    db: AsyncSession, *, provider: str, state: ProviderState, changed_by: str | None
) -> None:
    """Set every slug of a logical provider to ``state`` (upsert).

    Raises:
        NotFoundError: ``provider`` is not a known logical provider.
    """
    lp = LOGICAL_PROVIDERS.get(provider)
    if lp is None:
        raise NotFoundError("unknown payment provider", provider=provider)
    stamp = now()
    existing = {
        r.provider: r
        for r in (
            await db.execute(
                select(PaymentProviderState).where(PaymentProviderState.provider.in_(lp.slugs))
            )
        ).scalars()
    }
    for slug in lp.slugs:
        row = existing.get(slug)
        if row is None:
            db.add(
                PaymentProviderState(
                    provider=slug, state=state, changed_by=changed_by, changed_at=stamp
                )
            )
        else:
            row.state = state
            row.changed_by = changed_by
            row.changed_at = stamp
    await db.flush()


async def trip_active_to_maintenance(
    db: AsyncSession, *, changed_by: str | None = None
) -> list[str]:
    """Put every currently-``active`` logical provider into ``maintenance``.

    ``disabled`` is left alone so a later «Включить» does not resurrect a
    provider the operator had already taken off the storefront. Already in
    ``maintenance`` is a no-op. Returns the logical keys that changed.
    """
    changed: list[str] = []
    for logical, lp in LOGICAL_PROVIDERS.items():
        states = await get_states(db, lp.slugs)
        if any(state == "disabled" for state in states.values()):
            continue
        if all(state == "maintenance" for state in states.values()):
            continue
        await set_logical_state(db, provider=logical, state="maintenance", changed_by=changed_by)
        changed.append(logical)
    return changed


async def get_state_rows(db: AsyncSession, slugs: list[str]) -> dict[str, PaymentProviderState]:
    """Raw rows for ``slugs`` (for ``changed_by``/``changed_at``); missing slugs are
    simply absent from the returned mapping rather than defaulted."""
    return {
        r.provider: r
        for r in (
            await db.execute(
                select(PaymentProviderState).where(PaymentProviderState.provider.in_(slugs))
            )
        ).scalars()
    }


def state_status(state: ProviderState) -> CustomerStatus | None:
    """Pure state→customer-status mapping (ignores config-availability).

    ``disabled`` → None (hide). Unit-testable without env/config.
    """
    if state == "disabled":
        return None
    return "maintenance" if state == "maintenance" else "active"


def customer_status(slug: str, state: ProviderState) -> CustomerStatus | None:
    """Customer-facing status: None means "don't show".

    None when the gateway is not config-available (no keys) OR when ``state`` is
    ``disabled``; otherwise the state's status.
    """
    gw = REGISTRY.get(slug)
    if gw is None or not gw.available:
        return None
    return state_status(state)


def _coerce(raw: str) -> ProviderState:
    return raw if raw in _VALID_STATES else "active"  # type: ignore[return-value]
