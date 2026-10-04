"""Import every gift card / voucher G2B, FazerCards and G-Engine sell, reseller-only.

Run inside the api container. Preview first (reads only), then apply:

    docker exec -i yupay-prod-api-1 python - < scripts/seed/2026-10-05_bulk_voucher_import.py
    docker exec -i -e APPLY=1 yupay-prod-api-1 python - < scripts/seed/2026-10-05_bulk_voucher_import.py

The vouchers half of the 2026-10 bulk import, with the top-up script's
decisions (all regions, reseller-only, 13% / 5%, NOVA skipped) and its
shape: a brand is (title, region, variant), a row is one denomination, the
cheapest supplier is primary, every supplier that sells the row is mapped,
a quote over 1.6× the cheapest is left off.

What differs from top-ups:

- **Identity.** Gift cards carry the country in words («Netflix Saudi
  Arabia(KSA)», «Steam Wallet Code Argentina», «Amazon (AE)») — a country
  table, not a region word list, and any bare two-letter code in brackets is
  a region. Brackets that are not a country are a variant («Yalla Ludo
  (Diamond)», «Eneba (EUR)»). Brand spellings are aliased («PSN» = «PlayStation
  Store Wallet» = «PlayStation», «Apple iTunes» = «App Store & iTunes»).
- **Denomination.** A face value with a currency anywhere in the name
  («60$ PSN USA», «Steam Wallet Code MYR 22», «1000 TRY») is the key, then a
  quantity with a unit («1000 Robux»), then the normalised name (passes,
  subscriptions, editions).
- **Stock.** A row the supplier reports at zero is not imported; the hourly
  sweep keeps stock current for the rest.
- **No form.** A code is a code; ``required_fields`` is empty.
- **Routing.** A voucher routes inventory-first with the oldest non-reserve
  mapping as fallback; our warehouse holds none of these, so the cheapest
  supplier is pinned with ``force_supplier`` exactly as for top-ups.
- **Name clashes.** A voucher brand whose title is a top-up brand we already
  sell (PUBG Mobile UC codes beside PUBG Mobile top-ups) gets « (Voucher)».

Existing voucher brands (Roblox, Discord, Minecraft, Standoff 2) are skipped
whole; their SKUs gain missing supplier mappings as fallbacks. Idempotent per
brand slug; each brand is its own transaction.
"""

from __future__ import annotations

import asyncio
import functools
import os
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import yupay.main  # noqa: F401 -- registers every model; a bare session cannot map Order
from sqlalchemy import select, text
from yupay.core.db import get_session_factory
from yupay.modules.catalog import admin_schemas as cs
from yupay.modules.catalog import admin_service as cat
from yupay.modules.catalog.models import Brand
from yupay.modules.fulfillment.suppliers import REGISTRY
from yupay.modules.integrations.catalog_sync_gengine import _gengine_client_or_none
from yupay.modules.integrations.catalog_sync_panel import client_or_none
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping
from yupay.modules.sourcing import service as sourcing

ADMIN_ID = "00000000-0000-7000-8000-000000000001"
APPLY = os.environ.get("APPLY") == "1"
GIFT_CARDS = "019fe85e-92b3-7551-989e-6556a2f99ae8"
MARGIN = Decimal("13")
B2B_MARKUP = Decimal("5")
PRICE_SPREAD = Decimal("1.6")
SORT_BASE = 2000
UPDATED_BY = "bulk-voucher-import"

# --- identity ----------------------------------------------------------------

COUNTRIES = {
    "usa": "US",
    "us": "US",
    "united states": "US",
    "america": "US",
    "uk": "UK",
    "united kingdom": "UK",
    "gb": "UK",
    "canada": "CA",
    "ca": "CA",
    "mexico": "MX",
    "maxico": "MX",
    "mx": "MX",
    "brazil": "BR",
    "br": "BR",
    "argentina": "AR",
    "chile": "CL",
    "colombia": "CO",
    "peru": "PE",
    "latam": "LATAM",
    "europe": "EU",
    "eu": "EU",
    "germany": "DE",
    "de": "DE",
    "france": "FR",
    "fr": "FR",
    "italy": "IT",
    "it": "IT",
    "spain": "ES",
    "es": "ES",
    "netherlands": "NL",
    "nl": "NL",
    "belgium": "BE",
    "be": "BE",
    "austria": "AT",
    "at": "AT",
    "portugal": "PT",
    "pt": "PT",
    "ireland": "IE",
    "ie": "IE",
    "sweden": "SE",
    "se": "SE",
    "poland": "PL",
    "pl": "PL",
    "switzerland": "CH",
    "ch": "CH",
    "norway": "NO",
    "no": "NO",
    "denmark": "DK",
    "dk": "DK",
    "finland": "FI",
    "fi": "FI",
    "greece": "GR",
    "gr": "GR",
    "czech": "CZ",
    "cz": "CZ",
    "hungary": "HU",
    "hu": "HU",
    "romania": "RO",
    "ro": "RO",
    "turkey": "TR",
    "tr": "TR",
    "russia": "RU",
    "ru": "RU",
    "ukraine": "UA",
    "ua": "UA",
    "kazakhstan": "KZ",
    "kz": "KZ",
    "uae": "AE",
    "ae": "AE",
    "united arab emirates": "AE",
    "saudi arabia": "SA",
    "saudi arabia ksa": "SA",
    "ksa": "SA",
    "sa": "SA",
    "egypt": "EG",
    "eg": "EG",
    "qatar": "QA",
    "qa": "QA",
    "kuwait": "KW",
    "kw": "KW",
    "bahrain": "BH",
    "bh": "BH",
    "oman": "OM",
    "om": "OM",
    "jordan": "JO",
    "jo": "JO",
    "lebanon": "LB",
    "lb": "LB",
    "israel": "IL",
    "il": "IL",
    "morocco": "MA",
    "ma": "MA",
    "india": "IN",
    "in": "IN",
    "pakistan": "PK",
    "pk": "PK",
    "bangladesh": "BD",
    "bd": "BD",
    "indonesia": "ID",
    "id": "ID",
    "malaysia": "MY",
    "my": "MY",
    "singapore": "SG",
    "sg": "SG",
    "philippines": "PH",
    "ph": "PH",
    "thailand": "TH",
    "th": "TH",
    "vietnam": "VN",
    "vn": "VN",
    "cambodia": "KH",
    "kh": "KH",
    "japan": "JP",
    "jp": "JP",
    "korea": "KR",
    "south korea": "KR",
    "kr": "KR",
    "china": "CN",
    "cn": "CN",
    "hong kong": "HK",
    "hk": "HK",
    "taiwan": "TW",
    "tw": "TW",
    "australia": "AU",
    "au": "AU",
    "new zealand": "NZ",
    "nz": "NZ",
    "south africa": "ZA",
    "za": "ZA",
    "nigeria": "NG",
    "ng": "NG",
    "kenya": "KE",
    "ke": "KE",
    "czech republic": "CZ",
    "slovakia": "SK",
    "croatia": "HR",
    "luxembourg": "LU",
    "belarus": "BY",
    "slovenia": "SI",
    "bulgaria": "BG",
    "serbia": "RS",
    "lithuania": "LT",
    "latvia": "LV",
    "estonia": "EE",
    "iceland": "IS",
    "cyprus": "CY",
    "malta": "MT",
    "uruguay": "UY",
    "costa rica": "CR",
    "euro area": "EU",
    "hongkong": "HK",
    "mena": "MENA",
    "uzbekistan": "UZ",
    "azerbaijan": "AZ",
    "algeria": "DZ",
    "tunisia": "TN",
    "iraq": "IQ",
    "maldives": "MV",
    "andorra": "AD",
    "global": "GLOBAL",
    "worldwide": "GLOBAL",
    "international": "GLOBAL",
    "cis": "CIS",
}
ALIASES = {
    # keys are post-strip titles: «Riot Access Code» has already lost «code»
    "riot access": "riot",
    "riot cash card": "riot",
    "riot cash": "riot",
    "valorant riot": "riot",
    "valorant vp": "valorant",
    "valorant riot cash": "valorant",
    "league of legends rp": "league of legends",
    "garena free fire": "free fire",
    "garena free fire official": "free fire",
    "discord nitro": "discord",
    "pubg mobile uc": "pubg mobile",
    "honor of kings token redeem": "honor of kings",
    "honor of kings token": "honor of kings",
    "telegram redeem": "telegram stars",
    "roblox robux": "roblox",
    "nintendo switch": "nintendo switch online",
    "nintendo switch online membership": "nintendo switch online",
    "apple itunes": "app store itunes",
    "itunes": "app store itunes",
    "app store and itunes": "app store itunes",
    "app store itunes": "app store itunes",
    "apple": "app store itunes",
    "steam wallet code": "steam",
    "steam wallet": "steam",
    "steam gift card": "steam",
    "psn": "playstation",
    "playstation network giftcards": "playstation",
    "playstation store wallet": "playstation",
    "playstation store": "playstation",
    "playstation network": "playstation",
    "playstation plus": "playstation plus",
    "nintendo eshop": "nintendo",
    "xbox gift card": "xbox",
    "xbox live": "xbox",
    "xbox game pass": "xbox game pass",
    "google play gift card": "google play",
    "googleplay": "google play",
    "riot points": "riot",
    "riot access code": "riot",
    "razer gold pin": "razer gold",
    "razer": "razer gold",
    "netease pay us giftcards": "netease pay",
    "imo giftcards": "imo",
    "jawaker gift cards": "jawaker",
    "garena free fire vouchers official": "free fire vouchers",
    "free fire vouchers": "free fire vouchers",
    "spotify premium": "spotify",
    "netflix gift card": "netflix",
    "amazon gift card": "amazon",
}
TRAILING = sorted(COUNTRIES, key=len, reverse=True)
CUR = {
    "$": "USD",
    "usd": "USD",
    "us$": "USD",
    "€": "EUR",
    "eur": "EUR",
    "£": "GBP",
    "gbp": "GBP",
    "₺": "TRY",
    "tl": "TRY",
    "try": "TRY",
    "lira": "TRY",
    "¥": "JPY",
    "jpy": "JPY",
    "yen": "JPY",
    "₹": "INR",
    "inr": "INR",
    "rs": "INR",
    "aed": "AED",
    "sar": "SAR",
    "sr": "SAR",
    "myr": "MYR",
    "rm": "MYR",
    "sgd": "SGD",
    "s$": "SGD",
    "php": "PHP",
    "₱": "PHP",
    "thb": "THB",
    "฿": "THB",
    "idr": "IDR",
    "rp": "IDR",
    "brl": "BRL",
    "r$": "BRL",
    "cad": "CAD",
    "c$": "CAD",
    "aud": "AUD",
    "a$": "AUD",
    "nzd": "NZD",
    "mxn": "MXN",
    "pln": "PLN",
    "zł": "PLN",
    "cny": "CNY",
    "rmb": "CNY",
    "hkd": "HKD",
    "hk$": "HKD",
    "twd": "TWD",
    "nt$": "TWD",
    "krw": "KRW",
    "₩": "KRW",
    "rub": "RUB",
    "₽": "RUB",
    "kzt": "KZT",
    "egp": "EGP",
    "qar": "QAR",
    "kwd": "KWD",
    "bhd": "BHD",
    "omr": "OMR",
    "chf": "CHF",
    "sek": "SEK",
    "nok": "NOK",
    "dkk": "DKK",
    "czk": "CZK",
    "huf": "HUF",
    "ron": "RON",
    "uah": "UAH",
    "zar": "ZAR",
    "ngn": "NGN",
    "kes": "KES",
    "vnd": "VND",
    "₫": "VND",
    "pkr": "PKR",
    "bdt": "BDT",
    "clp": "CLP",
    "cop": "COP",
    "pen": "PEN",
    "ars": "ARS",
    "ils": "ILS",
    "jod": "JOD",
    "mad": "MAD",
}


SYM = "|".join(re.escape(k) for k in sorted(CUR, key=len, reverse=True))
PAIR_A = re.compile(r"(?<![a-z0-9])(" + SYM + r")\s*(\d+(?:[.,]\d+)?)(?![\d])", re.I)
PAIR_B = re.compile(r"(\d+(?:[.,]\d+)?)\s*(" + SYM + r")(?![a-z])", re.I)
QTY = re.compile(r"(?<![\w.])(\d{1,7})\s*([a-z][a-z ]{1,24}?)(?=\s*[-(,]|$)", re.I)
SPECIAL = re.compile(
    r"month|year|week|day|membership|subscription|pass|edition|plus|premium|pack|bundle|key", re.I
)


def norm(t: str) -> str:
    t = t.lower().replace("&", " and ").replace("é", "e").replace("™", "").replace("®", "")
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# ISO 3166-1 alpha-2: a bare two-letter bracket is a region only when it is one
# of these («(EA)» is a platform, «(UZ)» is a country).
ISO2 = frozenset(
    [
        "ad",
        "ae",
        "af",
        "ag",
        "ai",
        "al",
        "am",
        "ao",
        "ar",
        "at",
        "au",
        "aw",
        "az",
        "ba",
        "bb",
        "bd",
        "be",
        "bf",
        "bg",
        "bh",
        "bi",
        "bj",
        "bn",
        "bo",
        "br",
        "bs",
        "bt",
        "bw",
        "by",
        "bz",
        "ca",
        "cd",
        "cf",
        "cg",
        "ch",
        "ci",
        "cl",
        "cm",
        "cn",
        "co",
        "cr",
        "cu",
        "cv",
        "cy",
        "cz",
        "de",
        "dj",
        "dk",
        "dm",
        "do",
        "dz",
        "ec",
        "ee",
        "eg",
        "er",
        "es",
        "et",
        "fi",
        "fj",
        "fm",
        "fr",
        "ga",
        "gb",
        "gd",
        "ge",
        "gh",
        "gm",
        "gn",
        "gq",
        "gr",
        "gt",
        "gw",
        "gy",
        "hk",
        "hn",
        "hr",
        "ht",
        "hu",
        "id",
        "ie",
        "il",
        "in",
        "iq",
        "ir",
        "is",
        "it",
        "jm",
        "jo",
        "jp",
        "ke",
        "kg",
        "kh",
        "ki",
        "km",
        "kn",
        "kp",
        "kr",
        "kw",
        "kz",
        "la",
        "lb",
        "lc",
        "li",
        "lk",
        "lr",
        "ls",
        "lt",
        "lu",
        "lv",
        "ly",
        "ma",
        "mc",
        "md",
        "me",
        "mg",
        "mh",
        "mk",
        "ml",
        "mm",
        "mn",
        "mo",
        "mr",
        "mt",
        "mu",
        "mv",
        "mw",
        "mx",
        "my",
        "mz",
        "na",
        "ne",
        "ng",
        "ni",
        "nl",
        "no",
        "np",
        "nr",
        "nz",
        "om",
        "pa",
        "pe",
        "pg",
        "ph",
        "pk",
        "pl",
        "pt",
        "pw",
        "py",
        "qa",
        "ro",
        "rs",
        "ru",
        "rw",
        "sa",
        "sb",
        "sc",
        "sd",
        "se",
        "sg",
        "si",
        "sk",
        "sl",
        "sm",
        "sn",
        "so",
        "sr",
        "st",
        "sv",
        "sy",
        "sz",
        "td",
        "tg",
        "th",
        "tj",
        "tl",
        "tm",
        "tn",
        "to",
        "tr",
        "tt",
        "tv",
        "tw",
        "tz",
        "ua",
        "ug",
        "uk",
        "us",
        "uy",
        "uz",
        "vc",
        "ve",
        "vn",
        "vu",
        "ws",
        "ye",
        "za",
        "zm",
        "zw",
    ]
)
SHORT_OK = {w for w in COUNTRIES if len(w) == 2}
CURRENCIES = {c.lower() for c in CUR.values()}
# Bracketed words that describe the listing, not the product.
BRACKET_NOISE = {"official", "digital", "minecoins"}
# Words in a quantity's unit that say where or how it is sold, not what it is.
UNIT_NOISE = {
    "global", "voucher", "vouchers", "code", "codes", "card", "cards", "gift", "pin", "pins",
    "redeem", "pack", "official", "key", "digital",
} | {w for w in COUNTRIES if " " not in w}  # fmt: skip
TIERS = {
    "ultimate", "core", "standard", "pc", "basic", "premium", "nitro", "plus", "essential",
    "extra", "deluxe", "family", "individual", "student", "duo", "mobile", "lite", "pro",
}  # fmt: skip
STRIP_WORDS = re.compile(
    r"\b(gift ?cards?|giftcards?|voucher codes?|vouchers?|digital code|e ?gift|code|codes|pin|pins)\b"
)


def identity(name: str) -> tuple[str, str, str]:
    """(title, region, variant) of a supplier game or category name."""
    region, variants = "GLOBAL", []
    for p in re.findall(r"\(([^)]*)\)", name):
        raw = p.strip()
        k = norm(raw)
        if k in COUNTRIES:
            region = COUNTRIES[k]
        elif raw.lower() in ISO2 and raw.isupper():
            region = raw.upper()
        elif k in BRACKET_NOISE or k in CURRENCIES:
            # «Eneba (EUR)» and «Eneba (USD)» are one shelf; the currency is on every row.
            continue
        else:
            variants.append(re.sub(r"[™®]", "", raw).strip())
    b = STRIP_WORDS.sub(" ", norm(name))
    b = re.sub(r"\s+", " ", b).strip()
    changed = True
    while changed:
        changed = False
        for w in TRAILING:
            if b != w and b.endswith(" " + w) and (len(w) > 2 or w in SHORT_OK):
                region = COUNTRIES[w]
                b = b[: -len(w) - 1].strip()
                changed = True
                break
        tail = b.rsplit(" ", 1)[-1]
        if " " in b and tail in CURRENCIES and len(tail) == 3:
            b = b.rsplit(" ", 1)[0]
            changed = True
    b = ALIASES.get(b, b)
    return b, region, " ".join(variants)


def region_in(title: str) -> str | None:
    """A country named inside a G2B product title («10$ PSN USA», «Amazon Germany 10 EUR»).

    G2B groups by category and puts the country in the row; the panel and
    G-Engine put it in the category. Two-letter codes count only in brackets."""
    for p in re.findall(r"\(([^)]*)\)", title):
        k = norm(p)
        if k in COUNTRIES:
            return COUNTRIES[k]
        if p.strip().lower() in ISO2 and p.strip().isupper():
            return p.strip().upper()
    words = norm(title)
    for w in TRAILING:
        if len(w) > 2 and re.search(rf"\b{re.escape(w)}\b", words):
            return COUNTRIES[w]
    return None


def _val(num: str) -> str:
    return format(Decimal(num.replace(",", ".")).normalize(), "f")


def _unit(words: str) -> str:
    """The thing being counted: the last word of the unit phrase once noise is gone."""
    kept = [w for w in words.split() if w not in UNIT_NOISE]
    if not kept or any(w in CURRENCIES for w in kept):
        return ""  # «1 USD Diamond» counts money, not diamonds
    return re.sub(r"s$", "", kept[-1])


PERIOD = re.compile(r"(?<![\w.])(\d{1,3})\s*[- ]?\s*(month|year|week|day)s?\b", re.I)
PLUS = re.compile(
    r"(?<![\w.])(\d{1,7})\s*\+\s*(\d{1,7})\s*([a-z][a-z ]{0,24}?)(?=\s*[-(,)]|$)", re.I
)


def qty_key(low: str) -> tuple[Any, ...] | None:
    """A quantity with a unit, bonus included: «2000 + 200 Halo Credits» is 2200 credits."""
    plus = PLUS.search(low)
    if plus:
        unit = _unit(plus.group(3).strip())
        if unit:
            return ("QTY", str(int(plus.group(1)) + int(plus.group(2))), unit)
    for q in QTY.finditer(low):
        unit = _unit(q.group(2).strip())
        # «Riot Cash 120 TRY - Valorant 375 VP»: the money is the price tag, the VP the count.
        if unit and unit not in CURRENCIES:
            return ("QTY", str(int(q.group(1))), unit)
    return None


def denom_key(name: str) -> tuple[Any, ...]:
    """What a row sells: a face value, else a period, else a quantity, else its name."""
    n = name.replace(" ", " ").strip()
    n = re.sub(r"(?<=\d),(?=\d{3}\b)", "", n)
    m = PAIR_B.search(n) or PAIR_A.search(n)
    if m:
        a, b = m.group(1), m.group(2)
        num, cur = (a, b) if a[0].isdigit() else (b, a)
        # «290 RP» is Riot Points; the rupiah is written «Rp».
        code = None if cur == "RP" else CUR.get(cur.lower())
        if code and float(num.replace(",", ".")) > 0:
            return ("VAL", _val(num), code)
    low = n.lower()
    period = PERIOD.search(low)
    if period:
        words = set(re.sub(r"[^a-z0-9 ]+", " ", low).split())
        return (
            "PERIOD",
            str(int(period.group(1))),
            period.group(2),
            " ".join(sorted(words & TIERS)),
        )
    if not SPECIAL.search(low):
        q = qty_key(low)
        if q:
            return q
    words = re.sub(r"[^a-z0-9 ]+", " ", low).split()
    return ("NAME", " ".join(words))


# Things a card can count beside its price; «10 Twitch Gift Card» counts nothing.
COUNTED = {
    "vp", "rp", "uc", "cp", "diamond", "token", "coin", "robux", "gold", "gem", "point", "credit",
    "star", "shell", "crystal", "minecoin", "buck", "v-buck", "vbuck", "ruby", "pearl", "cash",
}  # fmt: skip
QTY_TEXT = re.compile(r"(?<![\w.])(\d{1,7})\s*([A-Za-z][A-Za-z ]{0,24}?)(?=\s*[-(,)]|$)")


def _qty_text(name: str) -> str | None:
    """The counted thing as the supplier wrote it, bonus summed: «375 VP», «110 Diamonds»."""
    plus = PLUS.search(name)
    if plus and _unit(plus.group(3).strip().lower()) in COUNTED:
        return _cased(f"{int(plus.group(1)) + int(plus.group(2))} {plus.group(3).strip()}")
    for m in QTY_TEXT.finditer(name):
        if _unit(m.group(2).strip().lower()) in COUNTED:
            return _cased(f"{m.group(1)} {m.group(2).strip()}")
    return None


def _cased(label: str) -> str:
    """«16 TOKENS» → «16 Tokens», «1000 coins» → «1000 Coins»; «60 UC» stays."""
    out = []
    for w in label.split():
        if (w.isupper() and len(w) <= 3) or not (w.isupper() or w.islower()):
            out.append(w)
        else:
            out.append(w.capitalize())
    return " ".join(out)


def label_for(names: list[tuple[str, str]], key: tuple[Any, ...]) -> str:
    """Our shelf name: the face value and currency, else the quantity, else the longest name."""
    if key[0] == "VAL":
        # «120 TRY (375 VP)»: a priced card that also counts something says both.
        hint = next((h for _s, n in names if (h := _qty_text(n))), None)
        return f"{key[1]} {key[2]} ({hint})" if hint else f"{key[1]} {key[2]}"
    order = {"fzr": 0, "gengine": 1, "g2b": 2}
    ranked = sorted(names, key=lambda sn: (order[sn[0]], -len(sn[1])))
    if key[0] == "QTY":
        for _s, n in ranked:
            if re.match(r"^\s*[\d,]+\s+[A-Za-z]", n):
                return _cased(re.sub(r"\s+", " ", n).strip())
        return f"{key[1]} {key[2].title()}"
    return re.sub(r"\s+", " ", sorted(names, key=lambda sn: len(sn[1]), reverse=True)[0][1]).strip()


# --- fetch --------------------------------------------------------------------


async def _paced[T](call: Callable[[], Awaitable[T]], retries: int = 3) -> T:
    """One supplier call, retried through 429s (the panel says how long) and timeouts."""
    for _attempt in range(retries):
        try:
            return await call()
        except Exception as exc:
            msg = str(exc) or type(exc).__name__
            if "Timeout" in type(exc).__name__:
                await asyncio.sleep(2)
                continue
            if "429" not in msg and "Слишком много" not in msg:
                raise
            wait = re.search(r"(\d+)", msg)
            await asyncio.sleep(min(int(wait.group(1)) if wait else 30, 60))
    return await call()


async def fetch() -> list[dict[str, Any]]:
    """Every supplier gift-card game with its in-stock rows, read-only."""
    games: list[dict[str, Any]] = []
    g2b = REGISTRY["g2b"]._client()
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    # G2B ignores ``page``: every page is the same ~1200 rows, so one call.
    for p in await g2b.fetch_products(page=1, limit=1200):
        if p.get("stock") == 0 or not p.get("unit_price") or not p.get("id"):
            continue
        cat_title = str(p.get("category_title") or "").strip() or "?"
        # A category's rows may each name their own country («$10 PSN USA» under
        # «PlayStation Network GiftCards»): those rows form a game of their own.
        found = region_in(str(p.get("title") or ""))
        name = f"{cat_title} ({found})" if found and found != identity(cat_title)[1] else cat_title
        by_cat[name].append(p)
    for name, ps in by_cat.items():
        cat_title = str(ps[0].get("category_title") or "").strip() or "?"
        games.append({"s": "g2b", "id": cat_title, "name": name, "offers": [
            {"vid": str(p["id"]), "name": str(p.get("title") or ""), "cost": Decimal(str(p["unit_price"]))}
            for p in ps
        ]})  # fmt: skip
    fzr = client_or_none("fzr")
    assert fzr is not None, "FZR_API_KEY is not configured"
    for c in await fzr.list_giftcards():
        cid = str(c["category_id"])
        try:
            cards = await _paced(functools.partial(fzr.list_giftcard_cards, cid))
        except Exception as exc:  # noqa: BLE001
            print(f"  ! fzr {cid}: {exc!s:.80}")
            continue
        await asyncio.sleep(0.35)
        offers = [
            {
                "vid": str(x["card_id"]),
                "name": str(x.get("name") or ""),
                "cost": Decimal(str(x["price_usd"])),
            }
            for x in cards
            if x.get("price_usd") and (x.get("stock") or 0) > 0
        ]
        if offers:
            games.append({"s": "fzr", "id": cid, "name": str(c["name"]), "offers": offers})
    ge = _gengine_client_or_none()
    assert ge is not None, "GENGINE_API_KEY is not configured"
    prods: list[dict[str, Any]] = []
    for offset in range(0, 2000, 100):
        page = await ge.list_shop_products(limit=100, offset=offset)
        prods += page
        if len(page) < 100:
            break
    for p in prods:
        try:
            denoms = await ge.list_shop_denominations(int(p["id"]))
        except Exception as exc:  # noqa: BLE001
            print(f"  ! gengine {p.get('id')}: {exc!s:.80}")
            continue
        offers = [
            {
                "vid": str(d["id"]),
                "name": str(d.get("name") or ""),
                "cost": Decimal(str(d["price"])),
            }
            for d in denoms
            if d.get("price") is not None and (d.get("stock") or 0) > 0
        ]
        if offers:
            games.append(
                {"s": "gengine", "id": str(p["id"]), "name": str(p["name"]), "offers": offers}
            )
        await asyncio.sleep(0.2)
    return games


async def ours() -> list[dict[str, Any]]:
    async with get_session_factory()() as db:
        rows = await db.execute(text("""
            select b.slug brand, s.id sku_id, s.sku_code, s.cost_usdt, p.kind,
                   coalesce((select json_agg(json_build_object(
                       'supplier', m.supplier_slug, 'kind', m.kind,
                       'product', m.external_product_id, 'variant', m.external_variant_id))
                     from sku_supplier_mapping m where m.sku_id = s.id), '[]') maps
              from skus s join products p on p.id = s.product_id join brands b on b.id = p.brand_id
        """))  # fmt: skip
        return [dict(r) for r in rows.mappings().all()]


async def g2b_product_categories() -> dict[str, str]:
    """G2B voucher product id -> category title, so an existing mapping names its game."""
    out: dict[str, str] = {}
    for p in await REGISTRY["g2b"]._client().fetch_products(page=1, limit=1200):
        if p.get("id"):
            out[str(p["id"])] = str(p.get("category_title") or "").strip() or "?"
    return out


# --- plan ---------------------------------------------------------------------


def _slug(s: str) -> str:
    flat = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", flat.lower().replace("&", "and").replace("'", "")).strip("-")


DISPLAY = {
    "playstation": "PlayStation",
    "steam": "Steam Wallet",
    "app store itunes": "App Store & iTunes",
    "google play": "Google Play",
    "xbox": "Xbox",
    "nintendo": "Nintendo eShop",
    "razer gold": "Razer Gold",
    "riot": "Riot Access Code",
    "league of legends": "League of Legends RP",
    "valorant": "Valorant VP",
    "free fire": "Free Fire",
    "roblox": "Roblox",
    "netease pay": "NetEase Pay",
    "telegram stars": "Telegram Stars",
    "honor of kings": "Honor of Kings Tokens",
    "pubg mobile": "PUBG Mobile UC",
    "nintendo switch online": "Nintendo Switch Online",
}


def _brand_name(games: list[dict[str, Any]], region: str) -> str:
    """Our shelf name: the canonical title where one is known, else the first
    supplier's spelling with region, currency and «gift card» words removed,
    plus the region code in brackets."""
    order = {"fzr": 0, "gengine": 1, "g2b": 2}
    first = sorted(games, key=lambda g: order[g["s"]])[0]["name"]
    title, _region, variant = identity(first)
    if title in DISPLAY:
        shown = DISPLAY[title]
    else:
        shown = re.sub(r"[™®]", "", re.sub(r"\s*\([^)]*\)", "", first)).strip()
        shown = re.sub(r"\s*(gift ?cards?|giftcards?)\s*$", "", shown, flags=re.I).strip()
        low = shown.lower()
        for w in TRAILING:
            if COUNTRIES[w] == region and low.endswith(" " + w):
                shown, low = shown[: -len(w) - 1].rstrip(), low[: -len(w) - 1].rstrip()
                break
        if " " in low and low.rsplit(" ", 1)[-1] in CURRENCIES:
            shown = shown.rsplit(" ", 1)[0]
    suffix = " ".join(x for x in (region if region != "GLOBAL" else "", variant) if x)
    return f"{shown} ({suffix})" if suffix else shown


def _rows(games: list[dict[str, Any]]) -> dict[tuple[Any, ...], dict[str, list[dict[str, Any]]]]:
    rows: dict[tuple[Any, ...], dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for g in games:
        for o in g["offers"]:
            rows[denom_key(o["name"])][g["s"]].append({**o, "game": g["id"]})
    # «1 USD (100 + 10 Diamonds)» and «100+10 Diamonds» are one row: a quantity
    # row joins the face-value row whose names count the same thing.
    by_qty: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    for k, sup in rows.items():
        if k[0] == "VAL":
            for offers in sup.values():
                for o in offers:
                    q = qty_key(o["name"].lower())
                    if q:
                        by_qty.setdefault(q, k)
    for k in [k for k in list(rows) if k[0] == "QTY" and k in by_qty]:
        target = rows[by_qty[k]]
        for sup_slug, offers in rows.pop(k).items():
            target[sup_slug].extend(offers)
    # One supplier, two offers in one row: split them by full name, never collapse.
    for k in [k for k in list(rows) if any(len(v) > 1 for v in rows[k].values())]:
        sup = rows.pop(k)
        for s, offers in sup.items():
            for o in offers:
                full = re.sub(r"[^a-z0-9 ]+", " ", o["name"].lower()).strip()
                rows[("NAME", full)][s].append(o)
    return rows


def _price(cost: Decimal) -> Decimal:
    return (cost * (1 + MARGIN / 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def plan(  # noqa: PLR0912 -- one linear pass, read top to bottom
    games: list[dict[str, Any]], ours_rows: list[dict[str, Any]], g2b_cats: dict[str, str]
) -> dict[str, Any]:
    clusters: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for g in games:
        if "test" in norm(g["name"]).split():
            continue
        title, region, variant = identity(g["name"])
        # «Apex Legends (Xbox)» and «Apex Legends Xbox» are one shelf.
        folded = " ".join(sorted(set((title + " " + norm(variant)).split())))
        clusters[(folded, region, "")].append(g)
    owned: set[tuple[str, str]] = set()
    by_variant: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    for r in ours_rows:
        for m in r["maps"]:
            if m["kind"] != "voucher":
                continue
            game = (
                g2b_cats.get(m["product"], m["product"]) if m["supplier"] == "g2b" else m["product"]
            )
            owned.add((m["supplier"], game))
            by_variant[(m["supplier"], m["product"], m["variant"])] = r
    taken_slugs = {r["brand"] for r in ours_rows}
    topup_brands = {r["brand"] for r in ours_rows if r["kind"] == "top_up"}
    out: dict[str, Any] = {"new": [], "fallbacks": [], "deferred": [], "dropped": [], "flags": []}
    for ident, gs in sorted(clusters.items()):
        rows = _rows(gs)
        if any((g["s"], g["id"]) in owned for g in gs):
            _existing(out, rows, by_variant)
            continue
        skus = []
        for k, sup in rows.items():
            best = {s: min(v, key=lambda o: o["cost"]) for s, v in sup.items()}
            floor = min(o["cost"] for o in best.values())
            if floor <= 0:
                continue
            kept = {s: o for s, o in best.items() if o["cost"] <= floor * PRICE_SPREAD}
            out["dropped"] += [(ident, k, s) for s in set(best) - set(kept)]
            costs = [o["cost"] for o in kept.values()]
            if len(costs) > 1 and max(costs) > min(costs) * Decimal("1.3"):
                out["flags"].append((ident, k, {s: str(o["cost"]) for s, o in kept.items()}))
            primary = min(kept, key=lambda s: (kept[s]["cost"], s))
            skus.append({"denom": label_for([(s, o["name"]) for s, o in kept.items()], k)[:64],
                         "cost": kept[primary]["cost"], "primary": primary, "maps": kept, "key": k})  # fmt: skip
        if not skus:
            out["deferred"].append(
                (ident, "no in-stock priced rows", [f"{g['s']}:{g['id']}" for g in gs])
            )
            continue
        name = _brand_name(gs, ident[1])
        slug = _slug(name)[:64].strip("-")
        if slug in topup_brands or slug in taken_slugs:
            name = f"{name} (Voucher)" if "(" not in name else name.replace(")", ", Voucher)", 1)
            slug = _slug(name)[:64].strip("-")
        if slug in taken_slugs:
            out["deferred"].append(
                (ident, f"slug {slug} is taken", [f"{g['s']}:{g['id']}" for g in gs])
            )
            continue
        taken_slugs.add(slug)
        # Face values group by currency, then climb; everything else climbs by cost.
        skus.sort(
            key=lambda s: (s["key"][2] if s["key"][0] == "VAL" else "", s["cost"], s["denom"])
        )
        seen: Counter[str] = Counter()
        for s in skus:
            code = f"{slug}-{_slug(s['denom'])}"[:60].strip("-")
            seen[code] += 1
            s["code"] = code if seen[code] == 1 else f"{code[:57]}-{seen[code]}"
        out["new"].append({"slug": slug, "name": name, "region": ident[1][:8], "skus": skus,
                           "games": [f"{g['s']}:{g['id']}" for g in gs]})  # fmt: skip
    return out


def _existing(out: dict[str, Any], rows: dict[Any, Any], by_variant: dict[Any, Any]) -> None:
    for sup in rows.values():
        hit = None
        for s, offers in sup.items():
            for o in offers:
                hit = by_variant.get(
                    (s, o["vid"], None) if s == "g2b" else (s, o["game"], o["vid"])
                )
                if hit:
                    break
            if hit:
                break
        if hit is None:
            continue
        have = {m["supplier"] for m in hit["maps"]}
        ref = Decimal(str(hit["cost_usdt"])) if hit["cost_usdt"] is not None else None
        for s, offers in sup.items():
            o = min(offers, key=lambda x: x["cost"])
            if s in have or (ref and not ref / PRICE_SPREAD <= o["cost"] <= ref * PRICE_SPREAD):
                continue
            out["fallbacks"].append({"sku_id": hit["sku_id"], "code": hit["sku_code"], "supplier": s,
                                     "game": o["game"], "vid": o["vid"]})  # fmt: skip


# --- apply --------------------------------------------------------------------


def _mapping(sku_id: str, supplier: str, game: str, vid: str) -> MappingUpsert:
    return MappingUpsert(
        sku_id=sku_id,
        supplier_slug=supplier,
        kind="voucher",
        # G2B's voucher mapping is the product id alone; the panel's and
        # G-Engine's are category/product + card/denomination.
        external_product_id=vid if supplier == "g2b" else game,
        external_variant_id=None if supplier == "g2b" else vid,
        quantity=1,
        extra={},
        is_active=True,
        updated_by=UPDATED_BY,
    )


async def apply_brand(b: dict[str, Any], order: int) -> None:
    async with get_session_factory()() as db, db.begin():
        if (await db.execute(select(Brand.id).where(Brand.slug == b["slug"]))).first():
            return
        names = [cs.TranslationIn(locale=loc, name=b["name"]) for loc in ("ru", "en", "uz")]
        brand = await cat.create_brand(db, cs.BrandCreate(
            slug=b["slug"], category_id=GIFT_CARDS, sort_order=SORT_BASE + order,
            visible_retail=False, translations=names))  # fmt: skip
        brand.visible_b2b = True
        primaries = Counter(s["primary"] for s in b["skus"])
        product = await cat.create_product(db, cs.ProductCreate(
            slug=f"{b['slug'][:58]}-cards", brand_id=brand.id, kind="voucher",
            supplier_hint=primaries.most_common(1)[0][0], required_fields=[], translations=names))  # fmt: skip
        for i, s in enumerate(b["skus"]):
            sku = await cat.create_sku(db, cs.SkuCreate(
                product_id=product.id, sku_code=s["code"], denomination=s["denom"],
                region=b["region"], price_usd=_price(s["cost"]), cost_usdt=s["cost"],
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
            if await db.get(SkuSupplierMapping, (f["sku_id"], f["supplier"])) is None:
                await upsert_mapping(db, _mapping(f["sku_id"], f["supplier"], f["game"], f["vid"]))
                added += 1
    return added


async def main() -> None:
    print("Читаю каталоги поставщиков…")
    games = await fetch()
    p = plan(games, await ours(), await g2b_product_categories())
    n_sku = sum(len(b["skus"]) for b in p["new"])
    prim = Counter(s["primary"] for b in p["new"] for s in b["skus"])
    print(f"\nНовых брендов: {len(p['new'])}, SKU: {n_sku}, основной поставщик: {dict(prim)}")
    print(f"Фоллбеков в существующие SKU: {len(p['fallbacks'])}")
    print(f"Маппингов не создано из-за разброса цены >{PRICE_SPREAD}×: {len(p['dropped'])}")
    print(f"Строк с разбросом цены >1.3×: {len(p['flags'])}")
    print(f"Отложено: {len(p['deferred'])}")
    for ident, why, where in p["deferred"]:
        print(f"  - {' / '.join(x for x in ident if x)}: {why}  [{', '.join(where)}]")
    for b in p["new"]:
        print(f"  + {b['slug']:48s} {len(b['skus']):4d} SKU")
    if not APPLY:
        print("\nAPPLY не задан — ничего не записано.")
        return
    for i, b in enumerate(p["new"]):
        try:
            await apply_brand(b, i)
        except Exception as exc:  # noqa: BLE001 -- one brand must not stop the rest; re-run resumes
            print(f"  ! {b['slug']}: {exc!s:.200}")
    print(f"Фоллбеков добавлено: {await apply_fallbacks(p['fallbacks'])}")
    print("Готово.")


if __name__ == "__main__":
    asyncio.run(main())
