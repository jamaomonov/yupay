"""Generate the SEO + copy SQL for the six storefront brands of 2026-11-25.

Content lives in ``scripts/seed/brand_seo_2026_11_25/content_a.py`` (Valorant,
League of Legends, Fortnite) and ``content_b.py`` (Call of Duty: Mobile, EA SPORTS
FC 26, PUBG: BATTLEGROUNDS). Writes ``scripts/seed/2026-11-25_storefront5_seo.sql``:

- each brand's ru/en/uz ``seo_title``, ``seo_description``, ``short_description``,
  ``description``, ``instructions`` (the steps + delivery line) and ``highlights``;
- its FAQs, rebuilt;
- and, everywhere, the «комиссии сверху нет» line an earlier seed put into 41 FAQ
  answers: the owner's wording is that the total in so'm is shown before paying
  and exactly that is charged — never "no fee".

Run AFTER 2026-11-25_storefront5_regions.sql (it creates four of the brands).

    uv run python scripts/seed/build_brand_seo_2026_11_25.py
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
HERE = REPO / "scripts" / "seed" / "brand_seo_2026_11_25"
TARGET = REPO / "scripts" / "seed" / "2026-11-25_storefront5_seo.sql"
LOCALES = ("ru", "en", "uz")
CAPS = {"seo_title": 120, "seo_description": 320, "short": 512}

DELIVERY = {
    "code": {
        "ru": "Код появится на странице заказа и придёт на почту после оплаты.",
        "en": "The code appears on the order page and is emailed to you after payment.",
        "uz": "Kod toʻlovdan soʻng buyurtma sahifasida chiqadi va pochtaga keladi.",
    },
    "topup": {
        "ru": "CP зачисляются на аккаунт по ID игрока после оплаты. Пароль не нужен.",
        "en": "CP is credited to the account by Player ID after payment. No password needed.",
        "uz": "CP toʻlovdan soʻng oʻyinchi ID si orqali akkauntga tushadi. Parol kerak emas.",
    },
}
HOWTO = {
    "code": {
        "ru": "Как активировать код:",
        "en": "How to redeem the code:",
        "uz": "Kodni qanday faollashtirish:",
    },
    "topup": {"ru": "Как пополнить:", "en": "How to top up:", "uz": "Qanday toʻldirish:"},
}
HL = {
    "regions": {
        "ru": ["Оплата в сумах", "Код на почту", "Страна на выбор", "Без пароля"],
        "en": ["Pay in UZS", "Code by email", "Pick your country", "No password"],
        "uz": ["Soʻmda toʻlov", "Kod pochtaga", "Davlatni tanlang", "Parolsiz"],
    },
    "single": {
        "ru": ["Оплата в сумах", "Код на почту", "Без пароля"],
        "en": ["Pay in UZS", "Code by email", "No password"],
        "uz": ["Soʻmda toʻlov", "Kod pochtaga", "Parolsiz"],
    },
    "topup": {
        "ru": ["Оплата в сумах", "По ID игрока", "Без пароля", "Регион на выбор"],
        "en": ["Pay in UZS", "By Player ID", "No password", "Pick your region"],
        "uz": ["Soʻmda toʻlov", "Oʻyinchi ID orqali", "Parolsiz", "Hududni tanlang"],
    },
}
KIND = {
    "valorant": ("code", "regions"),
    "league-of-legends": ("code", "regions"),
    "fortnite": ("code", "regions"),
    "call-of-duty-mobile": ("topup", "topup"),
    "ea-sports-fc-26-ea-points": ("code", "single"),
    "pubg-battlegrounds": ("code", "single"),
}
#: The banned «no fee» line an earlier seed wrote, and what replaces it.
NO_FEE = {
    "ru": (
        " Итог в сумах виден до подтверждения, комиссии сверху нет.",
        " Итог в сумах виден до оплаты, и списывается ровно он.",
    ),
    "en": (
        " The total in soʻm is shown before you confirm, with no extra fee.",
        " The total in soʻm is shown before you pay, and exactly that is charged.",
    ),
    "uz": (
        " Yakuniy summa soʻmda tasdiqlashdan oldin koʻrinadi, ustiga komissiya yoʻq.",
        " Yakuniy summa soʻmda toʻlovdan oldin koʻrinadi va aynan u yechiladi.",
    ),
}


def load(name: str) -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return dict(mod.B)


def lit(text: str, tag: str = "c") -> str:
    if f"${tag}$" in text:
        raise SystemExit(f"copy contains ${tag}$")
    return f"${tag}${text}${tag}$"


def brand_sql(slug: str, d: dict[str, Any]) -> str:
    how, hl = KIND[slug]
    out = [f"\n-- {slug}\n"]
    for loc in LOCALES:
        for field, cap in CAPS.items():
            if len(d[field][loc]) > cap:
                raise SystemExit(f"{slug}.{field}.{loc} is {len(d[field][loc])} > {cap}")
        steps = "\n".join(f"{i}. {s}" for i, s in enumerate(d["steps"][loc], 1))
        instr = f"{HOWTO[how][loc]}\n\n{steps}\n\n{DELIVERY[how][loc]}"
        out.append(
            "UPDATE brand_translations SET\n"
            f"    seo_title = {lit(d['seo_title'][loc])},\n"
            f"    seo_description = {lit(d['seo_description'][loc])},\n"
            f"    short_description = {lit(d['short'][loc])},\n"
            f"    description = {lit(d['desc'][loc])},\n"
            f"    instructions = {lit(instr)},\n"
            f"    highlights = {lit(json.dumps(HL[hl][loc], ensure_ascii=False))}::json\n"
            f"WHERE brand_id = (SELECT id FROM brands WHERE slug = '{slug}') AND locale = '{loc}';\n"
        )
    out.append(
        f"DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = '{slug}');\n"
    )
    rows = [
        f"    ({i}, '{loc}', {lit(q[loc], 'q')}, {lit(a[loc], 'a')})"
        for i, (q, a) in enumerate(d["faqs"], 1)
        for loc in LOCALES
    ]
    sorts = ", ".join(f"({i})" for i in range(1, len(d["faqs"]) + 1))
    out.append(
        "WITH nf AS (\n"
        "    INSERT INTO brand_faqs (id, brand_id, sort_order, active)\n"
        "    SELECT gen_random_uuid(), b.id, v.so, true\n"
        f"      FROM brands b, (VALUES {sorts}) AS v(so)\n"
        f"     WHERE b.slug = '{slug}'\n"
        "    RETURNING id, sort_order\n"
        ")\n"
        "INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)\n"
        "SELECT nf.id, t.locale, t.question, t.answer\n"
        "  FROM nf JOIN (VALUES\n" + ",\n".join(rows) + "\n"
        ") AS t(so, locale, question, answer) ON t.so = nf.sort_order;\n"
    )
    return "".join(out)


def main() -> None:
    brands = {**load("content_a"), **load("content_b")}
    # The copy is for the EA app (PC) card, which is the retail FC 26 brand.
    brands["ea-sports-fc-26-ea-points"] = brands.pop("ea-sports-fc-26")
    missing = set(KIND) - set(brands)
    if missing:
        raise SystemExit(f"no content for {sorted(missing)}")
    out = [
        "-- GENERATED by scripts/seed/build_brand_seo_2026_11_25.py — do not edit by hand.\n"
        "-- SEO and copy for Valorant, League of Legends, Fortnite, Call of Duty: Mobile,\n"
        "-- EA SPORTS FC 26 and PUBG: BATTLEGROUNDS; and the «no fee» FAQ line replaced\n"
        "-- everywhere. Run after 2026-11-25_storefront5_regions.sql. Idempotent.\n\n"
        "BEGIN;\n"
    ]
    for slug in KIND:
        out.append(brand_sql(slug, brands[slug]))
    out.append("\n-- The owner's payment wording, everywhere an earlier seed said «no fee».\n")
    for loc, (old, new) in NO_FEE.items():
        out.append(
            f"UPDATE brand_faq_translations SET answer = replace(answer, {lit(old)}, {lit(new)})\n"
            f" WHERE locale = '{loc}' AND position({lit(old)} in answer) > 0;\n"
        )
    out.append(
        "\nSELECT b.slug, t.locale, t.seo_title,\n"
        "       (SELECT count(*) FROM brand_faqs f WHERE f.brand_id = b.id) AS faqs\n"
        "  FROM brands b JOIN brand_translations t ON t.brand_id = b.id\n"
        f" WHERE b.slug IN ({', '.join(repr(s) for s in KIND)})\n"
        " ORDER BY 1, 2;\n"
        "SELECT count(*) AS no_fee_left FROM brand_faq_translations\n"
        " WHERE answer ILIKE '%комиссии сверху нет%' OR answer ILIKE '%no extra fee%'\n"
        "    OR answer ILIKE '%ustiga komissiya yoʻq%';\n\n"
        "COMMIT;\n"
    )
    TARGET.write_text("".join(out), encoding="utf-8")
    print(f"wrote {TARGET.relative_to(REPO)}")


if __name__ == "__main__":
    main()
