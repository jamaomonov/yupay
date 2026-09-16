"""Pydantic DTOs for the ``gifts`` admin and public HTTP surfaces.

Public catalog DTOs (``GiftAppOut`` and friends) carry money as ``str``, not
``Decimal`` — same convention as the rest of the public wire format (see
AGENTS.md §9: minor-unit money is a string in transit). ``price_usd`` is our
2-dp sell price after margin; ``price_uzs`` is a whole-UZS display string,
``None`` when FX was unavailable for this request.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class GiftsAdminSettingsOut(BaseModel):
    """Current Steam Gifts settings, as shown on the admin settings page."""

    margin_percent: Decimal
    enabled: bool
    region_default: str
    regions: list[str]


class GiftsSettingsIn(BaseModel):
    """Admin edit of the margin percent.

    Bounded at the edge as well as in the column (``Numeric(10, 4)``,
    ``CHECK margin_percent >= 0``): 0-100 is the only range that makes sense
    for a percentage margin, and an unbounded ``Decimal`` would otherwise
    reach Postgres as a 500 rather than a 422 — same reasoning as
    ``fx.schemas.RateSettingIn.manual_rate``.
    """

    margin_percent: Decimal = Field(ge=0, le=100, max_digits=10, decimal_places=4)


class GiftAppOut(BaseModel):
    """One catalog row — a listing item, a DLC entry, or the top of a detail
    payload; all three share this shape upstream."""

    app_id: int
    name: str
    image: str | None
    type: str
    price_usd: str | None
    price_uzs: str | None
    discount_percent: int | None
    packages_count: int
    dlc_count: int


class GiftsListOut(BaseModel):
    """A page of :class:`GiftAppOut` rows plus the upstream total."""

    items: list[GiftAppOut]
    total: int


class GiftZonePriceOut(BaseModel):
    """Our sell price for one package, in one offered zone."""

    zone: str
    price_usd: str
    price_uzs: str | None


class GiftPackageOut(BaseModel):
    """One purchasable edition of a gift app, priced per offered zone."""

    id: int
    name: str
    image: str | None
    discount_percent: int | None
    prices: list[GiftZonePriceOut]


class GiftRegionOut(BaseModel):
    """One purchasable country, priced from the zone that covers it.

    The zone stays the pricing/wire unit (see
    ``yupay.modules.gifts.service.ZONE_COUNTRIES``); this is the
    buyer-facing unit a country picker renders. Every country covered by
    the same zone carries that zone's identical price — a CIS country's
    ``price_usd`` is the same number regardless of which of the nine CIS
    countries it is.
    """

    country: str
    zone: str
    price_usd: str
    price_uzs: str | None


class GiftProfileIn(BaseModel):
    """The pasted Steam link to check, carried in the request body.

    A body, not a query string, and deliberately so: the recipient's profile
    link *is* a third party's identity, and ``api.yupay.uz``'s Caddy site
    block writes a JSON access log whose ``uri`` field records the query
    string verbatim (``infra/caddy/Caddyfile.prod``), which promtail then
    ships to Loki. A ``GET ...?invite_url=steamcommunity.com/id/{vanity}``
    would therefore park that identifier in the logs — the very thing
    ``gifts.profile`` reduces to an opaque ``hash_short()`` everywhere it
    logs. Filtering the edge would work until the next unrelated Caddy edit
    undid it; not putting the identity in the URL cannot be undone by
    accident (2026-09-04 review).

    Nothing is lost by the method change: this endpoint is not bookmarkable,
    has no HTTP-caching story (its cache is server-side, in Redis), and is
    the same class of advisory identity lookup as
    ``POST /catalog/brands/{slug}/check-player``, which is already a POST
    for the same reason. It writes nothing, so — like ``check-player`` — it
    takes no ``Idempotency-Key``.
    """

    #: Bounded like the query parameter it replaced: a Steam profile/friend
    #: link never legitimately exceeds this (the longest accepted shape,
    #: ``s.team/p/{64 chars}``, is ~82), and an unbounded value is an
    #: unbounded number of distinct ``gifts:steam_profile`` cache keys for
    #: one upstream Steam call each.
    invite_url: str = Field(min_length=1, max_length=200)


class GiftProfileOut(BaseModel):
    """The pre-purchase recipient check: who a Steam link actually points to.

    ``status`` is the whole contract with the frontend, and the four values
    are deliberately not equally weighted. Only ``"not_found"`` — Steam's own
    "no such profile" — is a reason to stop the buyer. It comes from one of
    exactly two Steam answers: ``ResolveVanityURL`` reporting the documented
    ``success == 42`` ("No match") for an ``/id/{vanity}`` link, or
    ``GetPlayerSummaries`` returning an empty ``players`` array, which is
    Steam saying no account holds that steamid64 — the only existence check
    a ``/profiles/{steamid64}`` link ever gets.

    The other two mean "we could not get a definitive answer" for a reason
    that is ours, not the recipient's: ``"unsupported"`` is an ``s.team``
    friend-invite link the Web API cannot resolve at all, and
    ``"unavailable"`` covers everything else that can go wrong on our end
    (no API key configured, Steam unreachable, erroring or timing out, a
    response we could not parse, or a player row Steam *does* have but that
    carries neither a name nor an avatar — nothing to render is not the same
    as no such account: see ``gifts.profile.check_steam_profile``). The
    frontend is expected to treat ``"found"``, ``"unsupported"``, and
    ``"unavailable"`` identically: let the buyer continue.

    ``steam_id``/``nickname``/``avatar_url`` are only ever populated
    alongside ``status="found"`` — and ``"found"`` itself is only ever
    returned once at least one of ``nickname``/``avatar_url`` actually came
    back from Steam, so it never carries a persona with nothing to render
    (``nickname`` and ``avatar_url`` both ``None``). They are PII — never
    logged (see ``gifts.profile``).
    """

    status: Literal["found", "not_found", "unsupported", "unavailable"]
    steam_id: str | None
    nickname: str | None
    avatar_url: str | None


class GiftAppDetailOut(GiftAppOut):
    """Full app card: everything on :class:`GiftAppOut`, plus packages/DLC."""

    description: str | None
    packages: list[GiftPackageOut]
    dlc_total: int
    #: Deprecated (2026-09-03): kept for one release so a stale client that
    #: hasn't reloaded the country picker still renders. New clients read
    #: ``regions``/``region_default`` instead.
    zones: list[str]
    #: Deprecated (2026-09-03) — see ``zones`` above.
    zone_default: str
    regions: list[GiftRegionOut]
    region_default: str


__all__ = [
    "GiftAppDetailOut",
    "GiftAppOut",
    "GiftPackageOut",
    "GiftProfileIn",
    "GiftProfileOut",
    "GiftRegionOut",
    "GiftZonePriceOut",
    "GiftsAdminSettingsOut",
    "GiftsListOut",
    "GiftsSettingsIn",
]
