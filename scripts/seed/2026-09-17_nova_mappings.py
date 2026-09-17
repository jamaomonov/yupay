"""Match our SKUs to NOVA offers and write `nova` supplier mappings.

Run inside the api container so it can reach both the database and NOVA:

    docker compose -f docker-compose.prod.yml exec -T api \
        python - < scripts/seed/2026-09-17_nova_mappings.py

It is a **dry run** like that: it prints what it would write and saves nothing.
Read the tables, then run it again to commit:

    docker compose -f docker-compose.prod.yml exec -T -e APPLY=1 api \
        python - < scripts/seed/2026-09-17_nova_mappings.py

It pairs `Sku.denomination` with a NOVA offer name on **both** the number and
the unit — "1800 UC" is not "1800 WOW Coins", and NOVA sells both under one
PUBG category — and writes a mapping only when exactly one offer matches and
exactly one of our SKUs claims it. Everything else is printed for an operator
to finish in the admin: guessing which of "250 Coins" and "250 Coins + Epic
Box" a SKU meant is not a thing a script should do with money.

**A re-run re-asserts everything it wrote.** If an operator has since moved a
SKU back with Admin -> Sourcing -> «Авто», the next `APPLY=1` run puts
`force_supplier = nova` back on it. That is the right default for a seed — it
is how you fix a half-finished run — but it means a deliberate rollback and a
re-run disagree, and the re-run wins. The "switched to nova" table prints
before anything is committed, so read it.

Mappings are written ACTIVE. That is safe because auto sourcing skips reserve
suppliers entirely (`RESERVE_SUPPLIERS` in `integrations.models`, read by
`sourcing.service._resolve_auto`) — not merely because it prefers the oldest
mapping, which would leave a SKU with no incumbent routing itself to NOVA. An
order goes to NOVA when somebody sets `force_supplier = nova`, and at no other
time.

This script is now one of those somebodies, for brands listed in
`SWITCH_TO_NOVA`: it writes `force_supplier = nova` for every SKU it maps in
those brands, in the same transaction as the mapping. Every other mapped
brand — Mobile Legends, PUBG — stays reserve-only: mapped, routable by hand
later, but not switched by this run.

`pubg_mobile_auto` below is one of NOVA's four speed tiers for PUBG Mobile
(`_auto`, `_fast`, `_manual`, `_reserve` — same game, different fulfilment
speed and price); this script picks `_auto` on a hunch. Confirm that pick
against the price table this script prints (its `price_usd` column) before
trusting the mapping, and repoint the entry below if a different tier is the
one we actually mean to sell.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.fulfillment.suppliers.nova_client import (
    NovaClient,
    NovaError,
    NovaUnavailableError,
)
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.sourcing.models import SkuSourcingRule

SUPPLIER_SLUG = "nova"
#: `updated_by` audit value written on every mapping row this script touches.
UPDATED_BY = "seed:2026-09-17_nova_mappings"

BRAND_CATEGORIES: dict[str, str] = {
    # our brand slug -> their TOP-UP category id (not the validate namespace)
    #
    # What to expect from each, measured against their live catalogue on
    # 2026-09-17 — so that an operator reading a long unmatched table knows
    # whether the script is working or the catalogues simply differ:
    #
    # - `mobile_legends_ru` is our RU ladder exactly: all nine denominations
    #   match, and only the two passes are left by hand.
    # - `mobile_legends_global` is a DIFFERENT ladder. They sell 14/42/70/140/
    #   284/355/429/716/1446…, we sell 86/172/257/275/344/429/514… — `429
    #   Diamonds` is the only number in both. Expect one match and twenty-six
    #   lines to read. Their global catalogue does carry our pass SKUs by name
    #   (Weekly Elite Pack, Twilight Pass, Monthly Elite Pack), which is a
    #   by-hand mapping worth making.
    # - `pubg_mobile_auto` sells UC *and* WOW Coins under one category, with
    #   the same numbers on both ladders. That pair is exactly why the matcher
    #   below keys on the unit as well as the number.
    # - `free_fire_cis` matches on the six diamond denominations exactly like
    #   the others; the three memberships (Weekly Lite, Weekly Membership,
    #   Monthly Membership) carry no number at all, so they are paired by hand
    #   in `SKU_OFFER_OVERRIDES` instead of matched here. Measured against
    #   NOVA's live catalogue on 2026-09-17, NOVA is cheaper on all nine of our
    #   SKUs (0.8-3.6%), which is why this brand is also in `SWITCH_TO_NOVA`.
    "mobile-legends-ru": "mobile_legends_ru",
    "mobile-legends": "mobile_legends_global",
    "pubg-mobile": "pubg_mobile_auto",
    "free-fire": "free_fire_cis",
}

#: SKUs whose label is a name rather than a denomination, paired by hand.
#:
#: The matcher keys on a number and a unit, which is what makes it safe — and
#: a membership has neither. Pairing these by *name* instead would be fuzzy
#: matching on the one axis where a wrong answer routes money to the wrong
#: product, so they are listed here, read once by a human, or not mapped at all.
SKU_OFFER_OVERRIDES: dict[str, str] = {
    "freefire_cis-weekly-lite": "weekly_lite",
    "freefire_cis-weekly-membership": "weekly_membership",
    "freefire_cis-monthly-membership": "monthly_membership",
}

#: Brands whose mapped SKUs also get their live sourcing switched to NOVA.
#:
#: NOVA is a reserve supplier (`RESERVE_SUPPLIERS`): auto sourcing never picks
#: it, so a mapping alone moves nothing — only a `force_supplier` rule does.
#: This seed writes one for every SKU it maps in a brand listed here.
#:
#: Mobile Legends and PUBG are deliberately absent: their mappings stay a
#: reserve, exactly as today. A seed that switched them too would move live
#: traffic nobody asked to move.
SWITCH_TO_NOVA: frozenset[str] = frozenset({"free-fire"})

#: A denomination label: a number, then the unit it counts.
_DENOM = re.compile(r"^\s*(\d+)\s*(.*)$")

#: A digit-grouping separator, and only that: a comma or a space with a digit on
#: each side. Matched this narrowly on purpose — a blanket space strip would
#: join a number to whatever followed it.
_GROUPING = re.compile(r"(?<=\d)[\s,\u00a0](?=\d)")

#: What a denomination sells: how many, and of what. Both halves are the key.
_Denomination = tuple[int, frozenset[str]]


def _denomination(text: str | None) -> _Denomination | None:
    """A label's number and its unit words, or ``None`` if it is not a denomination.

    ``"275 Diamonds"`` -> ``(275, {"diamonds"})``;
    ``"1800 WOW Coins"`` -> ``(1800, {"wow", "coins"})``;
    ``"Weekly Elite Pack"`` -> ``None``.

    **The number must start the label, and the unit is part of the key.** Both
    halves of that rule were paid for by real rows in our own catalogue:

    - Without the anchor, ``"Elite Pass LV1-100"`` parses as ``1`` and
      ``"Prime (1 Month)"`` as ``1``, and either would map a subscription onto
      whatever offer happens to sell one of something. Every real denomination
      we sell reads ``"<n> <unit>"``; every pack reads as words.
    - Without the unit, ``"1800 UC"`` and ``"1800 WOW Coins"`` — both live
      under the ``pubg-mobile`` brand — are the same key, and NOVA's
      ``"1800 UC"`` would have been written onto both. A customer buying WOW
      Coins would have been sent UC.

    A unit spelled differently on the two sides (their ``"275 Diamond"``
    against our ``"275 Diamonds"``) simply does not match, and lands in the
    unmatched table for a human. That is the direction to be wrong in.
    """
    if not text:
        return None
    # "1,800 UC" and "1 800 UC" are the same denomination as "1800 UC". Without
    # this the number would stop at the separator and the remainder would leak
    # into the unit set, which fails safe (nothing matches) but puts a baffling
    # line in the unmatched table.
    m = _DENOM.match(_GROUPING.sub("", text))
    if m is None:
        return None
    units = frozenset(w for w in re.split(r"[^0-9a-z]+", m.group(2).lower()) if w)
    return (int(m.group(1)), units)


def _label(denom: _Denomination) -> str:
    """A denomination as an operator reads it: ``"1800 uc"``."""
    amount, units = denom
    return f"{amount} {' '.join(sorted(units))}".strip()


def _sku_denomination(sku: Any) -> _Denomination | None:  # Any: a Sku ORM row.
    """What this SKU sells, as a number and a unit.

    ``denomination`` is the only field consulted: it is the operator-facing
    label and the one that carries the unit. ``units`` holds a bare number with
    no unit beside it, so it cannot answer the half of the question that keeps
    UC out of a WOW Coins SKU, and ``sku_code`` is an identifier rather than a
    label.
    """
    return _denomination(sku.denomination)


@dataclass(frozen=True)
class _Matched:
    """One SKU that landed on exactly one NOVA offer."""

    sku_code: str
    offer_name: str
    cost_usdt: Decimal | None
    price_usd: str


@dataclass(frozen=True)
class _Unmatched:
    """One SKU a human has to finish mapping in the admin."""

    sku_code: str
    denomination: str | None
    reason: str


async def _load_skus(session: AsyncSession, *, brand_slug: str) -> list[Sku]:
    """Every SKU of every active product under ``brand_slug``."""
    return list(
        (
            await session.execute(
                select(Sku)
                .join(Product, Product.id == Sku.product_id)
                .join(Brand, Brand.id == Product.brand_id)
                .where(Brand.slug == brand_slug, Product.active.is_(True))
                .order_by(Sku.sku_code)
            )
        )
        .scalars()
        .all()
    )


def _offers_by_denomination(
    offers: list[dict[str, Any]],
) -> dict[_Denomination, list[dict[str, Any]]]:
    """Group offers by number *and* unit, dropping offers that are not denominations."""
    by_denom: dict[_Denomination, list[dict[str, Any]]] = {}
    for offer in offers:
        denom = _denomination(str(offer.get("name") or ""))
        if denom is not None:
            by_denom.setdefault(denom, []).append(offer)
    return by_denom


#: The keys the adapter knows how to send, as the *values* of its own field map
#: — those are NOVA's names, which is what a category declares.
#:
#: Checked rather than assumed because the cost of being wrong is total and
#: silent until the first order: a category asking for a key we do not send gets
#: a refusal on **every** order, and a dry run would not show it, because the
#: dry run pairs SKUs with offers and never builds a payload. `free_fire_cis`
#: turned out to ask for `player_id` alone (verified live on 2026-09-18) — but
#: it was verified, and the next brand added here will not be unless this
#: check does it.
_ADAPTER_FIELD_KEYS = frozenset({"player_id", "server_id"})


def _declared_field_keys(body: dict[str, Any]) -> set[str]:
    """The input keys a category says it needs, from `GET /topups/offers`."""
    fields = body.get("fields")
    if not isinstance(fields, list):
        return set()
    return {str(f.get("key") or "").strip() for f in fields if isinstance(f, dict) and f.get("key")}


def _offers_by_id(offers: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Index offers by ``offer_id``, for the by-hand pairs in `SKU_OFFER_OVERRIDES`.

    A **list** per id, like :func:`_offers_by_denomination`, and for the same
    reason: an id that two offers share is an ambiguity, and this script's rule
    is that an ambiguity is reported rather than resolved. Keeping only the
    first would bind an override to whichever offer NOVA happened to list
    first, silently, in the one script whose output decides where a customer's
    money goes. Their catalogue has never done this; the guard costs one line
    and removes the need to keep believing that.
    """
    by_id: dict[str, list[dict[str, Any]]] = {}
    for offer in offers:
        offer_id = str(offer.get("offer_id") or "").strip()
        if offer_id:
            by_id.setdefault(offer_id, []).append(offer)
    return by_id


def _upsert_stmt(  # Any: an Insert whose generic parameters SQLAlchemy does not export.
    *, sku_id: str, category_id: str, offer_id: str
) -> Any:
    """The ``ON CONFLICT (sku_id, supplier_slug) DO UPDATE`` for one mapping."""
    return (
        pg_insert(SkuSupplierMapping)
        .values(
            sku_id=sku_id,
            supplier_slug=SUPPLIER_SLUG,
            kind="game",
            external_product_id=category_id,
            external_variant_id=offer_id,
            is_active=True,
            updated_by=UPDATED_BY,
        )
        .on_conflict_do_update(
            index_elements=[SkuSupplierMapping.sku_id, SkuSupplierMapping.supplier_slug],
            set_={
                "kind": "game",
                "external_product_id": category_id,
                "external_variant_id": offer_id,
                "is_active": True,
                "updated_by": UPDATED_BY,
                # The column has a server default but no `onupdate`, so a
                # second write would otherwise keep the first one's timestamp —
                # and "when did this SKU move to NOVA?" is exactly the question
                # an audit asks of a row this script wrote.
                "updated_at": func.now(),
            },
        )
    )


def _upsert_switch_stmt(*, sku_id: str) -> Any:  # Any: see `_upsert_stmt` above.
    """The ``ON CONFLICT (sku_id) DO UPDATE`` that forces one SKU's sourcing onto NOVA.

    NOVA is a reserve supplier (`RESERVE_SUPPLIERS`): auto sourcing never picks
    it, however old its mapping. Writing this row is the only thing that does
    — and it is only ever called for a SKU already mapped above, and only for
    a brand in `SWITCH_TO_NOVA`.
    """
    return (
        pg_insert(SkuSourcingRule)
        .values(
            sku_id=sku_id,
            mode="force_supplier",
            supplier_slug=SUPPLIER_SLUG,
            updated_by=UPDATED_BY,
        )
        .on_conflict_do_update(
            index_elements=[SkuSourcingRule.sku_id],
            set_={
                "mode": "force_supplier",
                "supplier_slug": SUPPLIER_SLUG,
                "updated_by": UPDATED_BY,
                # The column has a server default but no `onupdate`, so a
                # second write would otherwise keep the first one's timestamp —
                # and "when did this SKU move to NOVA?" is exactly the question
                # an audit asks of a row this script wrote.
                "updated_at": func.now(),
            },
        )
    )


def _override_claim(
    sku: Any,  # Any: a Sku ORM row.
    *,
    by_id: dict[str, list[dict[str, Any]]],
    category_id: str,
) -> dict[str, Any] | _Unmatched | None:
    """This SKU's `SKU_OFFER_OVERRIDES` entry resolved against NOVA's offers.

    ``None`` means the SKU has no override — fall through to the number-and-
    unit matcher. Anything else — an offer or an `_Unmatched` — is final: an
    override is a human's answer, not a hint for the matcher to double-check.
    """
    override_offer_id = SKU_OFFER_OVERRIDES.get(sku.sku_code)
    if override_offer_id is None:
        return None
    candidates = by_id.get(override_offer_id, [])
    if not candidates:
        return _Unmatched(
            sku.sku_code,
            sku.denomination,
            f"override offer_id {override_offer_id!r} not found in nova's"
            f" {category_id} offers — check SKU_OFFER_OVERRIDES or map it by hand",
        )
    if len(candidates) > 1:
        names = ", ".join(str(c.get("name")) for c in candidates)
        return _Unmatched(
            sku.sku_code,
            sku.denomination,
            f"override offer_id {override_offer_id!r} matches {len(candidates)} nova"
            f" offers ({names}) — their catalogue is ambiguous here, pick one by hand",
        )
    return candidates[0]


def _claim_for_sku(
    sku: Any,  # Any: a Sku ORM row.
    *,
    by_denom: dict[_Denomination, list[dict[str, Any]]],
    by_id: dict[str, list[dict[str, Any]]],
    category_id: str,
) -> dict[str, Any] | _Unmatched:
    """This SKU's one candidate NOVA offer, or the reason it has none.

    `SKU_OFFER_OVERRIDES` is consulted first via `_override_claim` — see the
    module docstring for why a membership is paired by hand instead of by the
    matcher below. Either way the result still passes through
    `_match_brand`'s claims-and-collisions pass, so an override cannot
    double-claim an offer any more than a denomination match can.
    """
    override = _override_claim(sku, by_id=by_id, category_id=category_id)
    if override is not None:
        return override

    denom = _sku_denomination(sku)
    if denom is None:
        return _Unmatched(
            sku.sku_code,
            sku.denomination,
            "not a denomination label (a pack or a subscription) — map it by hand",
        )

    candidates = by_denom.get(denom, [])
    if not candidates:
        return _Unmatched(
            sku.sku_code,
            sku.denomination,
            f"no NOVA offer for {_label(denom)} in {category_id} — map it by hand",
        )
    if len(candidates) > 1:
        names = ", ".join(str(c.get("name")) for c in candidates)
        return _Unmatched(
            sku.sku_code,
            sku.denomination,
            f"{_label(denom)} matches {len(candidates)} nova offers ({names}) — pick one by hand",
        )

    offer = candidates[0]
    if not str(offer.get("offer_id") or "").strip():
        offer_name = str(offer.get("name") or "")
        return _Unmatched(
            sku.sku_code,
            sku.denomination,
            f"matched offer {offer_name!r} has no offer_id — map it by hand",
        )
    return offer


async def _match_brand(
    session: AsyncSession, client: NovaClient, *, brand_slug: str, category_id: str
) -> tuple[list[_Matched], list[_Unmatched], list[str]]:
    """Load one brand's SKUs, fetch NOVA's offers, pair them, upsert the matches.

    Pairing itself (override or denomination) is `_claim_for_sku`. When
    `brand_slug` is in `SWITCH_TO_NOVA`, every SKU this writes a mapping for
    also gets its sourcing forced onto NOVA; the third return value lists
    which SKUs that was.
    """
    skus = await _load_skus(session, brand_slug=brand_slug)
    if not skus:
        print(f"{brand_slug} ({category_id}): no active SKUs — skipping")
        return [], [], []

    try:
        body = await client.get_offers(category_id)
    except (NovaError, NovaUnavailableError) as exc:
        raise SystemExit(f"cannot reach NOVA: {exc}") from exc

    offers = [o for o in (body.get("offers") or []) if isinstance(o, dict)]
    by_denom = _offers_by_denomination(offers)
    by_id = _offers_by_id(offers)
    keys = _declared_field_keys(body)
    print(
        f"{brand_slug} ({category_id}): {len(skus)} sku(s), {len(offers)} nova offer(s),"
        f" fields {sorted(keys) or '(none declared)'}"
    )
    unknown = sorted(k for k in keys if k not in _ADAPTER_FIELD_KEYS)
    if unknown:
        raise SystemExit(
            f"{category_id} asks for input we cannot send: {unknown}. The adapter builds NOVA's"
            f" `fields` from {sorted(_ADAPTER_FIELD_KEYS)} only (`_FIELD_MAP` in"
            " fulfillment/suppliers/nova.py), so every order on this category would be refused."
            " Teach the adapter that key first, or drop this brand from BRAND_CATEGORIES."
        )

    # Two passes on purpose. The first decides; the second writes. Nothing is
    # upserted until every SKU of the brand has been resolved, because the last
    # guard below can only be applied once they all have: two of OUR SKUs can
    # land on one offer, and neither of them may be written when they do.
    claims: list[tuple[Any, dict[str, Any]]] = []
    matched: list[_Matched] = []
    unmatched: list[_Unmatched] = []
    switched: list[str] = []
    for sku in skus:
        claim = _claim_for_sku(sku, by_denom=by_denom, by_id=by_id, category_id=category_id)
        if isinstance(claim, _Unmatched):
            unmatched.append(claim)
            continue
        claims.append((sku, claim))

    # The mirror of the guard above, on our side of the pairing. NOVA's catalogue
    # is not the only one that can be ambiguous: a legacy row, a duplicate, or a
    # product whose label happens to read like a plain top-up can leave two of
    # our active SKUs claiming one offer. Writing both would send two different
    # products to the same thing, and the only trace would be two rows with the
    # same offer name in a table nobody reads twice. So neither is written.
    claimants: dict[str, list[str]] = {}
    for sku, offer in claims:
        claimants.setdefault(str(offer.get("offer_id") or "").strip(), []).append(sku.sku_code)

    for sku, offer in claims:
        offer_id = str(offer.get("offer_id") or "").strip()
        offer_name = str(offer.get("name") or "")
        rivals = claimants[offer_id]
        if len(rivals) > 1:
            others = ", ".join(c for c in rivals if c != sku.sku_code)
            unmatched.append(
                _Unmatched(
                    sku.sku_code,
                    sku.denomination,
                    f"{len(rivals)} of our SKUs claim {offer_name!r} ({others}) — map them by hand",
                )
            )
            continue
        await session.execute(
            _upsert_stmt(sku_id=sku.id, category_id=category_id, offer_id=offer_id)
        )
        matched.append(
            _Matched(sku.sku_code, offer_name, sku.cost_usdt, str(offer.get("price_usd") or ""))
        )
        if brand_slug in SWITCH_TO_NOVA:
            # Switching is what moves money — only for a SKU this run just
            # mapped, and only for a brand an operator put in the set above.
            await session.execute(_upsert_switch_stmt(sku_id=sku.id))
            switched.append(sku.sku_code)

    return matched, unmatched, switched


def _print_matched(rows: list[_Matched]) -> None:
    print(f"\nmatched ({len(rows)}):")
    if not rows:
        print("  (none)")
        return
    sku_w = max(len("sku_code"), *(len(r.sku_code) for r in rows))
    offer_w = max(len("nova offer"), *(len(r.offer_name) for r in rows))
    print(
        f"  {'sku_code'.ljust(sku_w)}  {'nova offer'.ljust(offer_w)}  {'cost_usdt':>10}  price_usd"
    )
    for r in rows:
        cost = str(r.cost_usdt) if r.cost_usdt is not None else "-"
        print(
            f"  {r.sku_code.ljust(sku_w)}  {r.offer_name.ljust(offer_w)}  {cost:>10}  {r.price_usd}"
        )


def _print_unmatched(rows: list[_Unmatched]) -> None:
    print(f"\nunmatched ({len(rows)}) — finish these in the admin:")
    if not rows:
        print("  (none)")
        return
    sku_w = max(len("sku_code"), *(len(r.sku_code) for r in rows))
    denom_w = max(len("denomination"), *(len(r.denomination or "-") for r in rows))
    print(f"  {'sku_code'.ljust(sku_w)}  {'denomination'.ljust(denom_w)}  why")
    for r in rows:
        denom = r.denomination or "-"
        print(f"  {r.sku_code.ljust(sku_w)}  {denom.ljust(denom_w)}  {r.reason}")


def _print_switched(rows: list[str]) -> None:
    """SKUs whose sourcing now forces NOVA — printed apart from `matched`.

    Mapping and switching are different acts with different consequences: a
    mapping is inert until something forces a SKU onto it, switching is the
    act that moves live orders. An operator should not have to infer which of
    the printed tables did which.
    """
    print(f"\nswitched to nova ({len(rows)}):")
    if not rows:
        print("  (none)")
        return
    for sku_code in rows:
        print(f"  {sku_code}")


async def main() -> None:
    """Pair our SKUs with NOVA's offers, print what that would do, and — only
    when told to — write it.

    **A dry run by default.** This script stopped being a mapping seed the day
    it started writing ``force_supplier`` rules: a mapping is inert until
    somebody routes to it, but a rule moves the next customer's order. Printing
    the tables and committing in the same breath left "check the output" as
    something an operator does *after* the routing changed. Now the tables come
    first and `APPLY=1` is the second step.
    """
    apply = os.environ.get("APPLY", "").strip().lower() in {"1", "true", "yes"}
    settings = get_settings()
    if not settings.nova_api_key:
        raise SystemExit("no NOVA API key configured — set NOVA_API_KEY and retry")

    client = NovaClient(
        api_key=settings.nova_api_key,
        base_url=settings.nova_base_url,
        timeout_seconds=settings.nova_request_timeout_seconds,
    )

    # Printed first, because switching a brand to NOVA is a promise their wallet
    # has to keep. A SKU that costs more than the balance does not fail at the
    # seed; it fails at a customer's checkout, which is a worse place to find out.
    try:
        balance = (await client.get_balance()).get("balance")
        print(f"nova balance: ${balance}")
    except (NovaError, NovaUnavailableError) as exc:
        raise SystemExit(f"cannot reach NOVA: {exc}") from exc

    all_matched: list[_Matched] = []
    all_unmatched: list[_Unmatched] = []
    all_switched: list[str] = []

    async with get_session_factory()() as session:
        for brand_slug, category_id in BRAND_CATEGORIES.items():
            matched, unmatched, switched = await _match_brand(
                session, client, brand_slug=brand_slug, category_id=category_id
            )
            all_matched += matched
            all_unmatched += unmatched
            all_switched += switched

        _print_matched(all_matched)
        _print_switched(all_switched)
        _print_unmatched(all_unmatched)

        if apply:
            await session.commit()
        else:
            await session.rollback()

    verb = "written" if apply else "would be written"
    print(
        f"\n{len(all_matched)} mapping(s) {verb}, {len(all_switched)} switched to nova,"
        f" {len(all_unmatched)} sku(s) left for the admin"
    )
    if not apply:
        print(
            "\nDRY RUN — nothing was saved. Read the tables above, then re-run with"
            " APPLY=1 to commit."
        )


if __name__ == "__main__":
    asyncio.run(main())
