"""Import every top-up game G2B, FazerCards and G-Engine sell, reseller-only.

Run inside the api container. Preview first (reads only), then apply:

    docker exec -i yupay-prod-api-1 python - < scripts/seed/2026-10-04_bulk_topup_import.py
    docker exec -i -e APPLY=1 yupay-prod-api-1 python - < scripts/seed/2026-10-04_bulk_topup_import.py

Owner decisions (2026-10-04):

- **Everything**, regional variants included (Free Fire BR, Valorant MY, …),
  with the region in the brand name. NOVA is skipped — it resells fzr — and so
  are fzr's «PUBG Mobile (Manual / Fast / Reserve)».
- **Reseller-only**: brand active, ``visible_b2b`` on, ``visible_retail`` off
  (ADR-0095). No logos, SEO or translations yet; retail can be switched on per
  brand later from the brands filter.
- **Margin 13% retail, 5% B2B**, on the cost of the supplier the SKU routes to.

How the matching works — names differ between suppliers, so a name is never
the key on its own:

- **Game** = (title, region, variant). Titles are normalised through an alias
  table (Freefire = Free Fire, TFT Mobile = Teamfight Tactics, …); the region
  comes from parentheses, a trailing word or G2B's code suffix; «Login Mode /
  Auto Via Login», Exclusive, Special, Instant, MAX are variants of their own.
- **Denomination** = the *total* quantity plus its unit — «156 + 16 Diamonds»
  (fzr), «156 Diamonds + 16 Bonus» (G-Engine) and «172» (G2B) are one row.
  First-top-up bonus rungs are their own rows, never a plain pack. A G2B bare
  number joins a unit row only when the game has one unit at that quantity
  (Genshin's «60» is not Chronal Nexus). Passes and bundles match on their
  normalised words, digits kept («Package 1» ≠ «Package 2»).
- **Price guard**: a supplier quoting over 1.6× the cheapest for the same row
  is not mapped to it — the same name at that spread is a different product.

Routing: the cheapest supplier is primary. ``fzr`` is a reserve supplier that
auto-routing skips, and two mappings written in one transaction tie on age and
fall to slug order, so a ``force_supplier`` rule pins every SKU whose primary
is fzr, or G-Engine with a G2B mapping beside it. The others stay mapped as
the comparison screen's numbers and the operator's reassign targets.

Deferred, printed at the end: «Login» variants (they take the buyer's account
password), games whose forms need a field beyond the account id and server
(character name, platform, …), and games with no priced offer.

Existing brands are not given new SKUs — they are on the storefront, and a new
SKU there would be retail too. Their missing rungs are counted; their existing
SKUs gain any missing supplier mapping as a fallback, never overwriting one.

Idempotent: an existing brand slug is skipped whole; each brand is its own
transaction, so a re-run picks up where a failure stopped.
"""

from __future__ import annotations

import asyncio
import os
import re
import unicodedata
from collections import Counter, defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select, text
from yupay.core.db import get_session_factory
from yupay.modules.catalog import admin_schemas as cs
from yupay.modules.catalog import admin_service as cat
from yupay.modules.catalog.models import Brand
from yupay.modules.fulfillment.suppliers import REGISTRY
from yupay.modules.integrations.catalog_sync_gengine import (
    _gengine_client_or_none,
    _list_all_services,
    sync_gengine_catalog,
)
from yupay.modules.integrations.catalog_sync_panel import client_or_none
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping
from yupay.modules.sourcing import service as sourcing

ADMIN_ID = "00000000-0000-7000-8000-000000000001"
APPLY = os.environ.get("APPLY") == "1"
TOP_UPS = "019f6a61-5db6-76a1-901f-54e1a9ad3c48"
MARGIN = Decimal("13")
B2B_MARKUP = Decimal("5")
PRICE_SPREAD = Decimal("1.6")
SORT_BASE = 1000

SKIP_GAMES = {
    ("g2b", "test"),
    ("fzr", "pubg_mobile_fast"),
    ("fzr", "pubg_mobile_manual"),
    ("fzr", "pubg_mobile_reserve"),
}
#: Own flows already: amount-priced Steam / Stars, Fragment Premium, gamepasses.
SKIP_TITLES = {"steam", "telegram", "telegram premium", "roblox gamepass"}

# --- game identity -------------------------------------------------------------

REGIONS = {
    "indonesia": "ID", "id": "ID", "philippines": "PH", "ph": "PH", "malaysia": "MY",
    "my": "MY", "singapore": "SG", "sg": "SG", "sgmy": "MY/SG", "my/sg": "MY/SG", "sg/my": "MY/SG",
    "thailand": "TH", "th": "TH", "vietnam": "VN", "vn": "VN", "cambodia": "KH", "kh": "KH",
    "brazil": "BR", "br": "BR", "latam": "LATAM", "mena": "MENA", "middle east": "MENA",
    "me": "MENA", "turkey": "TR", "tr": "TR", "russia": "RU", "ru": "RU", "cis": "CIS",
    "europe": "EU", "eu": "EU", "global": "GLOBAL", "united states": "US", "us": "US",
    "na": "NA", "north america": "NA", "americas": "AMERICAS", "asia": "ASIA", "sea": "SEA",
    "tw": "TW", "taiwan": "TW", "bangladesh": "BD", "bd": "BD", "naeu": "NAEU", "ca": "CA",
    "in": "IN", "kz": "KZ", "sa": "SA", "tw/hk/mo": "TW/HK/MO",
}  # fmt: skip
REGION_LABEL = {"ASIA": "Asia", "AMERICAS": "Americas"}
VARIANTS = {
    "login mode": "LOGIN", "auto via login": "LOGIN", "login": "LOGIN", "exclusive": "Exclusive",
    "special": "Special", "instant": "Instant", "max": "MAX", "garena": "Garena",
    "activision": "Activision",
}  # fmt: skip
ALIASES = {
    "freefire": "free fire", "garena free fire": "free fire", "aceracer": "ace racer",
    "gov nikke": "goddess of victory nikke", "nikke": "goddess of victory nikke",
    "eafc mobile": "ea fc mobile", "bigo live diamonds": "bigo live",
    "mobile legends bang bang": "mobile legends", "magic chess go go": "magic chess gogo",
    "magic chess": "magic chess gogo", "teamfight tactics": "tft mobile",
    "garena deltaforce": "delta force garena", "garena delta force": "delta force garena",
    "sky cotl": "sky children of the light", "the ants underground kingdom": "the ants",
    "the lord of the rings rise to war": "lord of the rings rise to war",
    "ragnarok x next generation": "ragnarok x", "puzzles survival": "puzzles and survival",
    "modern warships naval battles": "modern warships",
    "harry potter magic awaken": "harry potter magic awakened",
    "hatsune miku colorful stage": "hatsune miku", "soul land new world global": "soul land new world",
    "lds login": "love and deepspace", "garena undawn": "undawn garena",
    "arknight endfield": "arknights endfield", "hago diamonds": "hago", "livu coins": "livu",
    "mico coins": "mico", "life makeover global": "life makeover",
    "overmortal idle sea": "overmortal idle", "kings choice sea": "kings choice",
    "haikyu fly high sea": "haikyu fly high", "black clover m asia": "black clover m",
    "r6 mobile": "rainbow six mobile", "eafc 24": "ea fc 24",
}  # fmt: skip
_SHORT_REGIONS = {
    "my",
    "sg",
    "ph",
    "id",
    "th",
    "vn",
    "kh",
    "br",
    "eu",
    "us",
    "na",
    "ru",
    "tr",
    "tw",
    "bd",
}
TRAILING = sorted((k for k in REGIONS if len(k) > 2 or k in _SHORT_REGIONS), key=len, reverse=True)
G2B_CODE_REGION = {
    "_my": "MY", "_ph": "PH", "_sg": "SG", "_id": "ID", "_th": "TH", "_vn": "VN", "_kh": "KH",
    "_br": "BR", "_tr": "TR", "_ru": "RU", "_eu": "EU", "_us": "US",
}  # fmt: skip


def _norm(t: str) -> str:
    t = t.lower().replace("&", " and ").replace("!", "")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/ ]+", " ", t)).strip()


def identity(supplier: str, game_id: str, name: str) -> tuple[str, str, str]:  # noqa: PLR0912 -- one normalisation, read top to bottom
    """(title, region, variant) for one supplier game."""
    region, variant = "GLOBAL", ""
    for part in re.findall(r"\(([^)]*)\)", name):
        p = _norm(part)
        if p in REGIONS:
            region = REGIONS[p]
        elif p in VARIANTS:
            variant = VARIANTS[p]
        elif p != "auto":
            variant = (variant + " " + part.strip()).strip()
    b = re.sub(r"\b(top up|topup)\b", "", _norm(re.sub(r"\([^)]*\)", " ", name))).strip()
    for word, tag in (("login mode", "LOGIN"), ("instant", "Instant"), ("exclusive", "Exclusive"),
                      ("special", "Special"), ("vng", "VNG")):  # fmt: skip
        if b.endswith(" " + word):
            b, variant = b[: -len(word) - 1].strip(), tag
    stripped = True
    while stripped:
        stripped = False
        for w in TRAILING:
            if b.endswith(" " + w) and len(b) > len(w) + 3:
                region, b, stripped = REGIONS[w], b[: -len(w) - 1].strip(), True
                break
    b = ALIASES.get(b, b)
    if b.startswith(("codm activision", "call of duty mobile activision")):
        b = "codm activision"
    if b.startswith(("call of duty mobile garena", "codm garena")):
        b = "codm garena"
    if supplier == "g2b":
        if game_id.endswith("_login"):
            variant = "LOGIN"
        if region == "GLOBAL":
            for suffix, code in G2B_CODE_REGION.items():
                if game_id.endswith(suffix):
                    region = code
        if game_id.startswith("fifa_futcoins_"):
            variant = game_id.rsplit("_", 1)[-1].upper()
    return b, region, variant


# --- denomination key ----------------------------------------------------------

FIRST = re.compile(r"first|1st|double|первое", re.I)
SPECIAL = re.compile(
    r"pass|weekly|monthly|membership|card|subscription|bundle|pack|prime|plus|elite|starlight|"
    r"welkin|battle|season|lite|vip|gift|express|privilege|package|offer|chest|bag|box|month|"
    r"week|day",
    re.I,
)
UNIT_ALIAS = {"unknown cash": "uc", "bc": "gold", "dm": "diamonds"}
NOISE = {"bonus", "x", "web", "top", "up", "global", "the"}


def denom_key(name: str) -> tuple[Any, ...]:
    low = name.replace(",", "").replace("\u00a0", " ").replace("'", "").lower()
    bare = re.sub(r"\(.*?\)", " ", low)
    first = bool(FIRST.search(low))
    plus = re.findall(r"(\d+)\s*(?:[a-z ]{0,20})?\+\s*(\d+)", bare)
    nums = re.findall(r"(?<![\w.])(\d{1,7})(?![\w.]*\d)", bare)
    total = int(plus[0][0]) + int(plus[0][1]) if plus else (int(nums[0]) if nums else None)
    words = [w for w in re.sub(r"[^a-z ]+", " ", bare).split() if w not in NOISE and w != "id"]
    unit = " ".join(words[:2])
    for alias, canon in UNIT_ALIAS.items():
        if unit == alias or unit.startswith(alias + " "):
            unit = canon
    unit = re.sub(r"s\b", "", unit)
    if total is None or (SPECIAL.search(low) and not re.match(r"^\s*\d", low)):
        # The whole name, brackets included: «Prime (1 Month)» and «Prime (3
        # Months)» are two products, and a key that dropped the brackets kept one.
        tagged = [w for w in re.sub(r"[^a-z0-9 ]+", " ", low).split() if w not in NOISE]
        return ("NAME", re.sub(r"s\b", "", " ".join(tagged)), first)
    return ("QTY", total, unit, first)


def label_for(names: list[tuple[str, str]], key: tuple[Any, ...]) -> str:
    """Our shelf name for a merged row.

    The most descriptive spelling wins: «Handful of Gems» over G2B's «Handful
    of», «Weekly Card» over «Weekly». A «base + bonus» spelling is rewritten as
    the total with the split in brackets — «172 Diamonds (156 + 16)» — unless the
    «unit» is a pack («1+1 Gift Pack»), where the total means nothing.
    """
    plus = re.compile(r"^\s*(\d+)\s*(?:([A-Za-z][A-Za-z .'-]*?)\s*)?\+\s*(\d+)\s*(.*)$")
    ranked = sorted(names, key=lambda sn: (bool(plus.match(sn[1])), len(sn[1])), reverse=True)
    name = ranked[0][1].strip()
    m = plus.match(name)
    if m and key[0] == "QTY":
        unit = (m.group(4) or m.group(2) or "").replace("Bonus", "").strip()
        if unit and not SPECIAL.search(unit):
            return re.sub(r"\s+", " ", f"{key[1]} {unit} ({m.group(1)} + {m.group(3)})").strip()
        name = sorted(names, key=lambda sn: len(sn[1]), reverse=True)[0][1].strip()
    return name


# --- fetch -------------------------------------------------------------------


async def _paced_offers(client: Any, category_id: str) -> dict[str, Any]:
    """``get_offers`` paced, waiting out one 429 — standalone so the preview runs on any deploy."""
    try:
        return await client.get_offers(category_id)  # type: ignore[no-any-return]
    except Exception as exc:
        if getattr(exc, "status", None) != 429:
            raise
        found = re.search(r"(\d+)", str(exc))
        await asyncio.sleep(min(int(found.group(1)) if found else 30, 60))
        return await client.get_offers(category_id)  # type: ignore[no-any-return]
    finally:
        await asyncio.sleep(0.35)


async def fetch() -> dict[str, Any]:
    """Every supplier game with its offers, read-only."""
    g2b = REGISTRY["g2b"]._client()
    games: list[dict[str, Any]] = []
    for g in await g2b.fetch_games():
        code = str(g["code"])
        try:
            offers = await g2b.games_catalogue(code)
        except Exception as exc:  # noqa: BLE001 -- one game must not stop the read
            print(f"  ! g2b {code}: {exc!s:.80}")
            continue
        try:
            fields = ((await g2b.games_fields(code)).get("info") or {}).get("fields") or []
        except Exception:  # noqa: BLE001 -- 16 games 404 «fields not available»: id only
            fields = ["userid"]
        games.append({"s": "g2b", "id": code, "name": g["name"], "fields": fields, "offers": [
            {"vid": o["name"], "name": o["name"], "cost": Decimal(str(o["amount"]))}
            for o in offers if o.get("amount") is not None
        ]})  # fmt: skip
    fzr = client_or_none("fzr")
    assert fzr is not None, "FZR_API_KEY is not configured"
    for c in await fzr.list_topups():
        cid = str(c["category_id"])
        try:
            body = await _paced_offers(fzr, cid)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! fzr {cid}: {exc!s:.80}")
            continue
        games.append({"s": "fzr", "id": cid, "name": c["name"], "fields": body.get("fields") or [],
                      "offers": [{"vid": o["offer_id"], "name": o["name"], "cost": Decimal(str(o["price_usd"]))}
                                 for o in body.get("offers") or [] if o.get("price_usd")]})  # fmt: skip
    gengine = _gengine_client_or_none()
    assert gengine is not None, "GENGINE_API_KEY is not configured"
    services, _ = await _list_all_services(gengine)
    for svc in services:
        if svc.get("type") != "fixed":
            continue
        games.append({"s": "gengine", "id": str(svc["id"]), "name": svc["name"],
                      "fields": [p["param_key"] for p in svc.get("params") or []],
                      "offers": [{"vid": str(o["id"]), "name": o["name"], "cost": Decimal(str(o["price"]))}
                                 for o in svc.get("denominations") or [] if o.get("price") is not None]})  # fmt: skip
    return {"games": [g for g in games if (g["s"], g["id"]) not in SKIP_GAMES]}


async def ours() -> list[dict[str, Any]]:
    """Every SKU we sell with its mappings — the existing-brand side of the plan."""
    async with get_session_factory()() as db:
        rows = await db.execute(text("""
            select b.slug brand, s.id sku_id, s.sku_code, s.cost_usdt,
                   coalesce((select json_agg(json_build_object(
                       'supplier', m.supplier_slug, 'kind', m.kind,
                       'product', m.external_product_id, 'variant', m.external_variant_id))
                     from sku_supplier_mapping m where m.sku_id = s.id), '[]') maps
              from skus s join products p on p.id = s.product_id join brands b on b.id = p.brand_id
        """))  # fmt: skip
        return [dict(r) for r in rows.mappings().all()]


# --- forms -----------------------------------------------------------------------

_SERVER_KEYS = {"server", "server_id", "zone", "zone_id", "region"}
_BARE_IDS = {"uid", "sid", "account"}
_PID = {"ru": "ID игрока", "en": "Player ID", "uz": "Oʻyinchi ID"}
_SERVER = {"ru": "Сервер", "en": "Server", "uz": "Server"}


def _is_id(key: str) -> bool:
    return (key.endswith("_id") and key not in _SERVER_KEYS) or key in _BARE_IDS


def form_for(games: list[dict[str, Any]]) -> tuple[list[dict[str, Any]] | None, str]:  # noqa: PLR0911, PLR0912 -- one refusal per reason
    """(required_fields, why-deferred). Account id always, plus a server when any supplier asks."""
    needs_server, options = False, None
    for g in games:
        if g["s"] == "fzr":
            keys = [f["key"].lower() for f in g["fields"]]
            if not keys:
                return None, "fzr declares no fields"
            if {"email", "password"} & set(keys):
                return None, "login (email/password)"
            extra = [k for k in keys if not _is_id(k) and k not in _SERVER_KEYS]
            if extra:
                return None, f"extra field «{extra[0]}»"
            if sum(_is_id(k) for k in keys) != 1:
                return None, "two identifiers"
            for f in g["fields"]:
                if f["key"].lower() in _SERVER_KEYS:
                    needs_server = True
                    options = f.get("options") or options
        elif g["s"] == "g2b":
            if "charname" in g["fields"]:
                return None, "extra field «charname»"
            needs_server = needs_server or "serverid" in g["fields"]
        else:
            if set(g["fields"]) - {"Account", "Region", "Server"}:
                return None, f"G-Engine params {sorted(g['fields'])}"
            needs_server = needs_server or bool({"Region", "Server"} & set(g["fields"]))
    form: list[dict[str, Any]] = [
        {"key": "player_id", "label": _PID, "type": "text", "required": True}
    ]
    if needs_server and options:
        form.append({"key": "server", "label": _SERVER, "type": "select", "required": True,
                     "options": [{"value": str(o["value"]),
                                  "label": {loc: str(o.get("label") or o["value"]) for loc in _PID}}
                                 for o in options]})  # fmt: skip
    elif needs_server:
        form.append({"key": "server", "label": _SERVER, "type": "text", "required": True})
    return form, ""


# --- plan ------------------------------------------------------------------------


def _slug(s: str) -> str:
    flat = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", flat.lower().replace("&", "and").replace("'", "")).strip("-")


def _brand_name(games: list[dict[str, Any]], region: str, variant: str) -> str:
    order = {"fzr": 0, "gengine": 1, "g2b": 2}
    title = re.sub(
        r"\s*\([^)]*\)", "", sorted(games, key=lambda g: order[g["s"]])[0]["name"]
    ).strip()
    words = title.split()
    # «Tarisland Asia» + ASIA, «Ballistic Hero VNG» + VNG: the suffix would say it twice.
    while len(words) > 1 and (
        REGIONS.get(words[-1].lower()) == region or words[-1].upper() == variant.upper()
    ):
        words.pop()
    title = " ".join(words)
    suffix = " ".join(
        x for x in (REGION_LABEL.get(region, region) if region != "GLOBAL" else "", variant) if x
    )
    return f"{title} ({suffix})" if suffix else title


DROPPED_BARE: list[str] = []


def _rows(games: list[dict[str, Any]]) -> dict[tuple[Any, ...], dict[str, list[dict[str, Any]]]]:  # noqa: PLR0912 -- four merge rules, read top to bottom
    rows: dict[tuple[Any, ...], dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for g in games:
        for o in g["offers"]:
            rows[denom_key(o["name"])][g["s"]].append({**o, "game": g["id"]})
    # A G2B bare number («60») joins the one unit row at that quantity, if there is one.
    for k in [k for k in list(rows) if k[0] == "QTY" and k[2] == ""]:
        twins = [t for t in rows if t[0] == "QTY" and t != k and t[1] == k[1] and t[3] == k[3]]
        if len(twins) == 1:
            for s, v in rows.pop(k).items():
                rows[twins[0]][s].extend(v)
        elif twins:
            # Two unit rows at that quantity («1800 UC» and «1800 WOW Coins»): a
            # SKU called «1800» sells nothing a buyer can name.
            DROPPED_BARE.extend(o["name"] for v in rows.pop(k).values() for o in v)
    # G2B drops the noun («Weekly» for «Weekly Pass», «Handful of» for «Handful of
    # Gems»): a NAME row whose words sit inside exactly one other NAME row's, from
    # suppliers that row lacks, is that row.
    names = [k for k in rows if k[0] == "NAME"]
    for k in names:
        if k not in rows:
            continue
        mine = set(k[1].split())
        supers = [
            t
            for t in names
            if t != k
            and t in rows
            and t[2] == k[2]
            and mine < set(t[1].split())
            and not (set(rows[t]) & set(rows[k]))
        ]
        if len(supers) == 1:
            for s, v in rows.pop(k).items():
                rows[supers[0]][s].extend(v)
    # «SuperPass» and «Super Pass» are one word apart: NAME rows equal with the
    # spaces taken out, from different suppliers, are one row.
    squashed: dict[str, tuple[Any, ...]] = {}
    for k in [k for k in list(rows) if k[0] == "NAME"]:
        flat = (k[1].replace(" ", ""), k[2])
        other = squashed.get(flat)  # type: ignore[arg-type]
        if other is not None and other in rows and not (set(rows[other]) & set(rows[k])):
            for s, v in rows.pop(k).items():
                rows[other][s].extend(v)
        else:
            squashed[flat] = k  # type: ignore[index]
    # One supplier, two offers in one row: never collapse to the cheaper one —
    # split them by full name instead.
    for k in [k for k in list(rows) if any(len(v) > 1 for v in rows[k].values())]:
        sup = rows.pop(k)
        for s, offers in sup.items():
            for o in offers:
                full = re.sub(r"[^a-z0-9 ]+", " ", o["name"].lower()).strip()
                rows[("NAME", full, k[-1])][s].append(o)
    return rows


def _price(cost: Decimal) -> Decimal:
    return (cost * (1 + MARGIN / 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def plan(data: dict[str, Any], ours_rows: list[dict[str, Any]]) -> dict[str, Any]:
    clusters: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for g in data["games"]:
        ident = identity(g["s"], g["id"], g["name"])
        if ident[0] not in SKIP_TITLES:
            clusters[ident].append(g)
    owned = {
        (m["supplier"], m["product"]): r["brand"]
        for r in ours_rows
        for m in r["maps"]
        if m["kind"] == "game"
    }
    by_variant = {
        (m["supplier"], m["product"], m["variant"]): r for r in ours_rows for m in r["maps"]
    }
    out: dict[str, Any] = {
        "new": [],
        "fallbacks": [],
        "deferred": [],
        "missing": 0,
        "dropped": [],
        "no_fzr_rung": 0,
    }
    taken = {r["brand"] for r in ours_rows}
    for ident, games in sorted(clusters.items()):
        rows = _rows(games)
        if any((g["s"], g["id"]) in owned for g in games):
            _existing(out, rows, by_variant)
            continue
        where = [f"{g['s']}:{g['id']}" for g in games]
        if ident[2] == "LOGIN":
            out["deferred"].append((ident, "login (email/password)", where))
            continue
        form, why = form_for(games)
        if form is None:
            out["deferred"].append((ident, why, where))
            continue
        # A server *select* is FazerCards' own option list and its values are
        # theirs («tw_hk_mo», «Amagi»); G2B and G-Engine want their own codes,
        # which nothing here can look up. Such a brand routes to fzr whatever
        # the price, and a rung fzr does not sell is not sold.
        fzr_only = any(f["key"] == "server" and f["type"] == "select" for f in form)
        skus = []
        for k, sup in rows.items():
            best = {s: min(v, key=lambda o: o["cost"]) for s, v in sup.items()}
            floor = min(o["cost"] for o in best.values())
            if floor <= 0:
                continue
            kept = {s: o for s, o in best.items() if o["cost"] <= floor * PRICE_SPREAD}
            out["dropped"] += [(ident, k, s) for s in set(best) - set(kept)]
            if fzr_only and "fzr" not in kept:
                out["no_fzr_rung"] += 1
                continue
            primary = "fzr" if fzr_only else min(kept, key=lambda s: (kept[s]["cost"], s))
            skus.append({"denom": label_for([(s, o["name"]) for s, o in kept.items()], k)[:64],
                         "cost": kept[primary]["cost"], "primary": primary, "maps": kept})  # fmt: skip
        if not skus:
            out["deferred"].append((ident, "no priced offers", where))
            continue
        name = _brand_name(games, ident[1], ident[2])
        slug = _slug(name)[:64].strip("-")
        if slug in taken:
            slug = _slug(name + " global")[:64].strip("-")
        taken.add(slug)
        skus.sort(key=lambda s: (s["cost"], s["denom"]))
        seen: Counter[str] = Counter()
        for s in skus:
            code = f"{slug}-{_slug(s['denom'])}"[:60].strip("-")
            seen[code] += 1
            s["code"] = code if seen[code] == 1 else f"{code[:57]}-{seen[code]}"
        out["new"].append(
            {"slug": slug, "name": name, "region": ident[1], "form": form, "skus": skus}
        )
    return out


def _existing(out: dict[str, Any], rows: dict[Any, Any], by_variant: dict[Any, Any]) -> None:
    for sup in rows.values():
        ours_row = next((by_variant[(s, o["game"], o["vid"])] for s, v in sup.items() for o in v
                         if (s, o["game"], o["vid"]) in by_variant), None)  # fmt: skip
        if ours_row is None:
            out["missing"] += 1
            continue
        have = {m["supplier"] for m in ours_row["maps"]}
        ref = Decimal(str(ours_row["cost_usdt"])) if ours_row["cost_usdt"] is not None else None
        for s, offers in sup.items():
            o = min(offers, key=lambda x: x["cost"])
            if s in have or (ref and not ref / PRICE_SPREAD <= o["cost"] <= ref * PRICE_SPREAD):
                continue
            out["fallbacks"].append({"sku_id": ours_row["sku_id"], "code": ours_row["sku_code"],
                                     "supplier": s, "game": o["game"], "vid": o["vid"]})  # fmt: skip


# --- apply -----------------------------------------------------------------------


def _mapping(sku_id: str, supplier: str, game: str, vid: str) -> MappingUpsert:
    return MappingUpsert(sku_id=sku_id, supplier_slug=supplier, kind="game", external_product_id=game,
                         external_variant_id=vid, quantity=1, extra={}, is_active=True,
                         updated_by="bulk-topup-import")  # fmt: skip


async def apply_brand(b: dict[str, Any], order: int) -> None:
    """One brand, its one product, its SKUs, mappings and pins — one transaction."""
    async with get_session_factory()() as db, db.begin():
        if (await db.execute(select(Brand.id).where(Brand.slug == b["slug"]))).first():
            return
        names = [cs.TranslationIn(locale=loc, name=b["name"]) for loc in ("ru", "en", "uz")]
        brand = await cat.create_brand(db, cs.BrandCreate(
            slug=b["slug"], category_id=TOP_UPS, sort_order=SORT_BASE + order,
            visible_retail=False, translations=names))  # fmt: skip
        brand.visible_b2b = True
        primaries = Counter(s["primary"] for s in b["skus"])
        product = await cat.create_product(db, cs.ProductCreate(
            slug=f"{b['slug']}-topup"[:128], brand_id=brand.id, kind="top_up",
            supplier_hint=primaries.most_common(1)[0][0],
            required_fields=b["form"], translations=names))  # fmt: skip
        for i, s in enumerate(b["skus"]):
            sku = await cat.create_sku(db, cs.SkuCreate(
                product_id=product.id, sku_code=s["code"], denomination=s["denom"],
                region=b["region"][:8], price_usd=_price(s["cost"]), cost_usdt=s["cost"],
                margin_percent=MARGIN, sort_order=i))  # fmt: skip
            sku.visible_b2b = True
            sku.b2b_markup_pct = B2B_MARKUP
            for supplier, o in s["maps"].items():
                await upsert_mapping(db, _mapping(sku.id, supplier, o["game"], o["vid"]))
            if s["primary"] == "fzr" or (s["primary"] == "gengine" and "g2b" in s["maps"]):
                await sourcing.set_rule(db, sku_id=sku.id, mode="force_supplier",
                                        supplier_slug=s["primary"], admin_id=ADMIN_ID)  # fmt: skip


async def apply_fallbacks(fallbacks: list[dict[str, Any]]) -> int:
    added = 0
    async with get_session_factory()() as db, db.begin():
        for f in fallbacks:
            exists = await db.get(SkuSupplierMapping, (f["sku_id"], f["supplier"]))
            if exists is None:
                await upsert_mapping(db, _mapping(f["sku_id"], f["supplier"], f["game"], f["vid"]))
                added += 1
    return added


async def main() -> None:
    print("Читаю каталоги поставщиков…")
    data = await fetch()
    p = plan(data, await ours())
    n_sku = sum(len(b["skus"]) for b in p["new"])
    prim = Counter(s["primary"] for b in p["new"] for s in b["skus"])
    print(f"\nНовых брендов: {len(p['new'])}, SKU: {n_sku}, основной поставщик: {dict(prim)}")
    print(f"Фоллбеков в существующие SKU: {len(p['fallbacks'])}")
    print(
        f"Номиналов поставщиков, которых нет в существующих брендах (не импортируются): {p['missing']}"
    )
    print(f"Маппингов не создано из-за разброса цены >{PRICE_SPREAD}×: {len(p['dropped'])}")
    print(f"Номиналов без единицы (G2B «1800» при UC и WOW Coins) пропущено: {len(DROPPED_BARE)}")
    print(f"Номиналов без fzr в брендах с выбором сервера пропущено: {p['no_fzr_rung']}")
    print(f"Отложено игр: {len(p['deferred'])}")
    for ident, why, where in p["deferred"]:
        print(f"  - {' / '.join(x for x in ident if x)}: {why}  [{', '.join(where)}]")
    for b in p["new"]:
        print(f"  + {b['slug']:44s} {len(b['skus']):4d} SKU  поля={[f['key'] for f in b['form']]}")
    if not APPLY:
        print("\nAPPLY не задан — ничего не записано.")
        return
    for i, b in enumerate(p["new"]):
        try:
            await apply_brand(b, i)
        except Exception as exc:  # noqa: BLE001 -- one brand must not stop the rest; re-run resumes
            print(f"  ! {b['slug']}: {exc!s:.200}")
    print(f"Фоллбеков добавлено: {await apply_fallbacks(p['fallbacks'])}")
    async with get_session_factory()() as db, db.begin():
        await sync_gengine_catalog(db)
    print("Готово.")


if __name__ == "__main__":
    asyncio.run(main())
