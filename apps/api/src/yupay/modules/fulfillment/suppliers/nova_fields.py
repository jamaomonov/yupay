"""Building NOVA's ``fields`` payload from NOVA's own declaration.

Until 2026-09-23 this was a fixed rename — our ``server`` became their
``server_id``, our ``player_id`` stayed ``player_id`` — and that is right for
some categories and wrong for others. NOVA declares the truth per category on
``GET /api/v2/topups/offers``, and across the twenty categories we map it
takes **four** different shapes:

- ``player_id`` alone — Free Fire, Blood Strike, PUBG, Honor of Kings, …
- ``player_id`` + ``server_id`` (free-form) — Mobile Legends, Magic Chess
- ``player_id`` + ``server`` (a **select**, values ``asia``/``america``/
  ``europe``/``tw_hk_mo``) — Genshin, Honkai Star Rail
- a differently named identifier entirely — ``imo_id``, ``likee_id``,
  ``bigo_id``

The fixed rename got two of those right by luck. Order ``01a0ce52`` (Honkai
Star Rail, 2026-09-23) was refused with ``Field "server" is required.``
because we had renamed it to ``server_id``; the ten IMO SKUs routed to NOVA
would have been refused the same way for ``imo_id``, and nobody had sent one
yet to find out.

So the shape is read rather than assumed. Our form keys map onto theirs by
**role**, not by name:

- their identifier — whatever ``*_id`` field is not a server — takes our
  ``player_id``;
- their server field takes our ``server``.

A ``select`` also needs its *value* translated: our form stores ``Europe``
(chosen to match G2B, the primary route for these games) and NOVA wants
``europe``. Matching is case-insensitive against their ``value`` first and
their ``label`` second, so a form written for one supplier still satisfies
the other without a per-category translation table.
"""

from __future__ import annotations

from typing import Any

from yupay.core.logging import get_logger

log = get_logger("yupay.fulfillment.nova_fields")

#: Our form keys that carry the account being credited, most specific first.
_OUR_IDENTIFIER_KEYS = ("player_id", "account", "imo_id", "likee_id", "bigo_id")

#: Our form keys that carry the server/zone.
_OUR_SERVER_KEYS = ("server", "server_id", "zone", "zone_id")

#: Their field keys that mean "which server", as opposed to "which account".
#: Everything else ending in ``_id`` is an identifier — see :func:`_role_of`.
_THEIR_SERVER_KEYS = frozenset({"server", "server_id", "zone", "zone_id", "region"})


def _role_of(their_key: str) -> str:
    """``"server"``, ``"identifier"`` or ``""`` for a field we cannot place.

    Derived rather than listed: a new NOVA category that calls its identifier
    ``foo_id`` is handled the day it appears, which is the whole point of
    reading their declaration instead of maintaining a table of our own.
    """
    key = their_key.strip().lower()
    if key in _THEIR_SERVER_KEYS:
        return "server"
    if key.endswith("_id") or key == "account":
        return "identifier"
    return ""


def _our_value(data: dict[str, Any], role: str, their_key: str) -> str:
    """Our form's value for one of their fields.

    An exact key match wins — if their field is literally ``player_id`` and
    our form has ``player_id``, no inference is involved. Only then does the
    role table decide.
    """
    exact = str(data.get(their_key) or "").strip()
    if exact:
        return exact
    if not role:
        # A field we cannot place — a promo code, an email, whatever they add
        # next. Inference here would send our player id under a name that
        # means something else entirely, which is worse than omitting it: NOVA
        # refuses a missing field by name, and silently accepts a wrong one.
        return ""
    candidates = _OUR_SERVER_KEYS if role == "server" else _OUR_IDENTIFIER_KEYS
    for key in candidates:
        value = str(data.get(key) or "").strip()
        if value:
            return value
    return ""


def _translate_option(value: str, options: list[dict[str, Any]]) -> str:
    """Our stored choice as one of their option values.

    Our forms were written against G2B, which capitalises (``Europe``,
    ``TW_HK_MO``); NOVA's enum is lower-case. Falling back to the label
    catches the other direction — a form storing the human word where they
    key on a code.

    An unmatched value is returned unchanged rather than dropped: NOVA
    refusing ``Europe`` with a message naming the field is far easier to read
    than an order silently placed with the server missing.
    """
    wanted = value.strip().casefold()
    for option in options:
        if str(option.get("value") or "").strip().casefold() == wanted:
            return str(option.get("value"))
    for option in options:
        label = option.get("label")
        text = label if isinstance(label, str) else ""
        if text.strip().casefold() == wanted:
            return str(option.get("value"))
    log.info("nova.option_not_in_enum", field_value=value)
    return value


def field_specs(offers_body: dict[str, Any]) -> list[dict[str, Any]]:
    """The ``fields`` NOVA declares for a category, or ``[]``.

    ``[]`` means "they told us nothing", which every caller must treat as
    "fall back to what we knew before" rather than "this category needs no
    fields" — the two look identical here and mean opposite things.
    """
    fields = offers_body.get("fields")
    return [f for f in fields if isinstance(f, dict)] if isinstance(fields, list) else []


def build_fields(specs: list[dict[str, Any]], data: dict[str, Any]) -> dict[str, str]:
    """NOVA's payload for one order, keyed the way this category asks.

    Args:
        specs: their declared fields, from :func:`field_specs`.
        data: our order line's ``fulfillment_data``.

    Returns:
        Their keys mapped to our values, skipping any field we cannot fill.
        A missing required field is deliberately **not** an error here: NOVA
        names the field it wants in its refusal, and that message is a better
        diagnosis than one this function could invent.
    """
    out: dict[str, str] = {}
    for spec in specs:
        their_key = str(spec.get("key") or "").strip()
        if not their_key:
            continue
        value = _our_value(data, _role_of(their_key), their_key)
        if not value:
            continue
        options = spec.get("options")
        if str(spec.get("type") or "") == "select" and isinstance(options, list):
            value = _translate_option(value, [o for o in options if isinstance(o, dict)])
        out[their_key] = value
    return out


__all__ = ["build_fields", "field_specs"]
