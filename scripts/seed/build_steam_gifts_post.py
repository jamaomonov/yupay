"""Generate `scripts/seed/steam_gifts_blog_post.sql` from the markdown below.

The body has to survive `blog.sanitize.sanitize_body`, whose allowlist is
fail-closed: an `<h1>`, a `<div>`, a `<span>`, a `style=` attribute — anything
not on the list — is dropped or unwrapped without an error. Hand-writing the
HTML and hoping is how a post ships with half its structure silently gone, so
the source here is markdown and the conversion runs through the project's own
`markdown_to_html` + `sanitize_body`. What the seed file contains is therefore
exactly what the API would have stored had an editor pasted the same markdown.

Run from the repo root:

    uv run python scripts/seed/build_steam_gifts_post.py

Regenerate and re-commit the .sql whenever the copy changes; do not edit the
generated file by hand.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "apps" / "api" / "src"))

from yupay.modules.blog.markdown_html import markdown_to_html  # noqa: E402
from yupay.modules.blog.sanitize import sanitize_body  # noqa: E402

#: Only used to validate image hosts, and this post has no images.
MEDIA_BASE = "https://media.yupay.uz"

SLUG_RU = "kak-kupit-igru-v-steam-iz-uzbekistana"
SLUG_EN = "how-to-buy-steam-games-from-uzbekistan"
SLUG_UZ = "ozbekistondan-steam-oyin-sotib-olish"

RU_TITLE = "Как купить игру в Steam из Узбекистана"
RU_EXCERPT = (
    "Узбекистанская карта в Steam не проходит, а цены для нашего региона редко самые низкие. "
    "Разбираем, как купить игру легально, за сумы и обычно дешевле, чем в самом Steam."
)
RU_SEO_TITLE = "Как купить игру в Steam из Узбекистана за сумы — YuPay"
RU_SEO_DESCRIPTION = (
    "Пошаговая инструкция: как купить игру в Steam из Узбекистана, оплатить сумами картой "
    "Uzcard или Humo и не ошибиться с регионом аккаунта. С реальным сравнением цен."
)

RU_BODY = """
Купить игру в Steam из Узбекистана — задача, у которой два разных препятствия, и
их обычно путают. Первое: узбекистанская карта в Steam чаще всего не проходит.
Второе, менее очевидное: даже когда оплата проходит, цена для нашего региона
редко оказывается самой низкой из возможных. Ниже — что с этим делать.

## Почему карта не проходит

Steam принимает оплату не отовсюду и не любыми картами. Uzcard и Humo — это
локальные платёжные системы, за пределами страны они не работают, а
международные карты есть далеко не у всех. Отсюда все обходные пути, которыми
полон интернет: чужие аккаунты, VPN, «пополню за процент». Часть из них просто
неудобна, часть откровенно опасна — про это в конце.

## Цена в Steam зависит от региона

Это ключевая вещь, про которую мало кто знает. У Steam нет одной цены на игру.
Издатель назначает разные цены для разных регионов, и разрыв бывает
двукратным. Цена для Узбекистана — не самая высокая в мире, но и не самая
низкая: соседние регионы часто дешевле.

Вот три реальных примера, снятых с витрины Steam в сентябре 2026 года:

| Игра | Steam для Узбекистана | Наша цена |
| --- | --- | --- |
| West Escape | $0.99 | $0.78 |
| Age of Empires IV | $27.99 | $21.20 |
| Black Myth: Wukong | $59.99 | $41.45 |

Скажем сразу и честно: так бывает не всегда. Мы проверили 21 случайную игру из
каталога — дешевле оказались 17, примерно вровень 2, и на двух играх мы были
дороже. Медианная экономия среди выигрышных — около 15%, максимальная доходила
до 54%. Поэтому правильная формулировка — «обычно дешевле», а не «всегда»; цену
видно до оплаты, так что сравнить можно самому за десять секунд.

## Подарок Steam, а не ключ

Способ, которым это работает легально, называется подарком Steam. Игра
покупается в том регионе, где она доступна, и отправляется на аккаунт
получателя штатным механизмом самого Steam — тем же, которым вы дарите игру
другу на день рождения.

Что из этого следует:

- Никаких ключей вводить не нужно. Игра появляется в библиотеке сама.
- Пароль от аккаунта не нужен никому. Достаточно публичной ссылки на профиль.
- Игра остаётся у получателя навсегда, как любая купленная.
- Аккаунт остаётся ваш. Никакого «общего» или «арендованного» аккаунта.

## Как купить: по шагам

1. Найдите игру в каталоге — поиском по названию.
2. Выберите издание, если их несколько, и регион аккаунта получателя.
3. Вставьте ссылку на профиль Steam. Ник и аватар покажутся сразу — это
   страховка от опечатки в ссылке.
4. Оплатите картой Uzcard или Humo через Click, Payme или Uzum.
5. Дождитесь подарка. Обычно он приходит в течение часа.

## Главная ошибка — регион аккаунта

Подарок можно принять только в том регионе, для которого он куплен. Если
аккаунт получателя числится за другой страной, Steam просто не даст нажать
«Принять» — и это самая частая причина, по которой заказ застревает.

Проверяется за полминуты: Steam → «Об аккаунте» → строка «Страна». Это тот
самый регион, который нужно выбрать при оформлении. Если не совпадает — лучше
выяснить до оплаты, а не после.

## Если игра оказалась дополнением

DLC работает только поверх основной игры. Подарить дополнение человеку, у
которого основной игры нет, технически можно — пользы от этого не будет
никакой, пока он не купит базовую версию. В карточке такие позиции помечены,
но на всякий случай стоит посмотреть.

## Про безопасность, коротко

Единственное, что нужно для подарка, — ссылка на профиль. Она публичная, её
видно любому.

Никто и никогда не должен просить у вас пароль от Steam, код из
Steam Guard или доступ к почте ради покупки игры. Если просят — это не
магазин, а кража аккаунта, и никакая цена этого не стоит. Правило простое и
не знает исключений.
""".strip()

EN_TITLE = "How to buy Steam games from Uzbekistan"
EN_EXCERPT = (
    "An Uzbek card usually will not go through on Steam, and the Uzbekistan price is rarely "
    "the lowest one. Here is how to buy a game legally, in sum, and usually cheaper."
)
EN_SEO_TITLE = "How to buy Steam games from Uzbekistan and pay in sum — YuPay"
EN_SEO_DESCRIPTION = (
    "A step-by-step guide: buying Steam games from Uzbekistan, paying in sum with an Uzcard "
    "or Humo card, and not getting the account region wrong. With a real price comparison."
)

EN_BODY = """
Buying a Steam game from Uzbekistan runs into two separate obstacles, and they
are usually confused with each other. First: an Uzbek card will most often not
go through on Steam. Second, and less obvious: even when payment does go
through, the price set for our region is rarely the lowest one available. Here
is what to do about both.

## Why the card is declined

Steam does not accept payment from everywhere or from every card. Uzcard and
Humo are domestic payment systems and do not work abroad, and international
cards are far from universal here. That is where the workarounds the internet
is full of come from: borrowed accounts, VPNs, "I'll top you up for a cut".
Some of those are merely inconvenient. Some are outright dangerous — more on
that at the end.

## A Steam price depends on the region

This is the part few people know. Steam does not have one price per game. The
publisher sets different prices for different regions, and the gap can be
twofold. The Uzbekistan price is not the highest in the world, but it is not
the lowest either: neighbouring regions are often cheaper.

Three real examples, read off Steam's own storefront in September 2026:

| Game | Steam for Uzbekistan | Our price |
| --- | --- | --- |
| West Escape | $0.99 | $0.78 |
| Age of Empires IV | $27.99 | $21.20 |
| Black Myth: Wukong | $59.99 | $41.45 |

To be straight about it: this is not always the case. We checked 21 randomly
picked titles from the catalogue — 17 came out cheaper, 2 were roughly level,
and on 2 of them we were dearer. The median saving among the wins was about
15%, the best reached 54%. So the honest wording is "usually cheaper", not
"always"; the price is shown before you pay, so checking takes ten seconds.

## A Steam gift, not a key

The mechanism that makes this legal is the Steam gift. The game is bought in a
region where it is available and sent to the recipient's account through
Steam's own gifting system — the same one you use for a friend's birthday.

What follows from that:

- There is no key to enter anywhere. The game simply appears in the library.
- Nobody needs your account password. A public profile link is enough.
- The game stays with the recipient for good, like any other purchase.
- The account stays yours. No shared account, no rented account.

## How to buy, step by step

1. Find the game in the catalogue by name.
2. Pick the edition, if there is more than one, and the recipient's account
   region.
3. Paste the Steam profile link. The nickname and avatar appear immediately —
   your insurance against a mistyped link.
4. Pay with an Uzcard or Humo card via Click, Payme or Uzum.
5. Wait for the gift. It usually arrives within an hour.

## The one mistake that matters: account region

A gift can only be accepted in the region it was bought for. If the
recipient's account belongs to a different country, Steam will simply not let
them click "Accept" — and that is the most common reason an order stalls.

Checking takes half a minute: Steam, then "Account details", then the
"Country" line. That is the region to pick at checkout. If it does not match,
find out before paying rather than after.

## If the title turns out to be DLC

DLC only works on top of the base game. You can technically gift an add-on to
someone who does not own the game, but it will do nothing at all until they
buy the base version. Such entries are marked on the card, but it is worth a
glance either way.

## On safety, briefly

The only thing a gift needs is a profile link. It is public; anyone can see
it.

Nobody should ever ask you for your Steam password, a Steam Guard code, or
access to your email in order to buy you a game. If they do, that is not a
shop, it is account theft, and no price is worth it. The rule is simple and
has no exceptions.
""".strip()

UZ_TITLE = "Oʻzbekistondan Steamda oʻyin qanday sotib olinadi"
UZ_EXCERPT = (
    "Oʻzbek kartasi Steamda koʻpincha oʻtmaydi, mintaqamiz uchun narx esa kamdan-kam eng past "
    "boʻladi. Oʻyinni qonuniy, soʻmda va odatda arzonroq sotib olish yoʻlini koʻrib chiqamiz."
)
UZ_SEO_TITLE = "Oʻzbekistondan Steamda oʻyinni soʻmda sotib olish — YuPay"
UZ_SEO_DESCRIPTION = (
    "Bosqichma-bosqich qoʻllanma: Oʻzbekistondan Steam oʻyinini sotib olish, Uzcard yoki Humo "
    "bilan soʻmda toʻlash va akkaunt mintaqasida xato qilmaslik. Haqiqiy narx solishtiruvi bilan."
)

UZ_BODY = """
Oʻzbekistondan Steamda oʻyin sotib olishda ikkita alohida toʻsiq bor va ular
odatda bir-biri bilan chalkashtiriladi. Birinchisi: oʻzbek kartasi Steamda
koʻpincha oʻtmaydi. Ikkinchisi, kamroq koʻzga tashlanadigani: toʻlov oʻtgan
taqdirda ham mintaqamiz uchun belgilangan narx kamdan-kam eng past boʻladi.
Quyida ikkalasi bilan nima qilish kerakligi.

## Nega karta oʻtmaydi

Steam hamma joydan va har qanday karta bilan toʻlovni qabul qilmaydi. Uzcard
va Humo — ichki toʻlov tizimlari, ular chet elda ishlamaydi, xalqaro kartalar
esa hammada ham yoʻq. Internet toʻla boʻlgan aylanma yoʻllar shundan kelib
chiqadi: begona akkauntlar, VPN, «foiz evaziga toʻldirib beraman». Ularning
bir qismi shunchaki noqulay. Bir qismi esa ochiqdan-ochiq xavfli — bu haqda
oxirida.

## Steamdagi narx mintaqaga bogʻliq

Bu koʻpchilik bilmaydigan asosiy jihat. Steamda oʻyinning yagona narxi yoʻq.
Nashriyotchi turli mintaqalar uchun turli narx belgilaydi va farq ikki
barobargacha boʻlishi mumkin. Oʻzbekiston uchun narx dunyodagi eng yuqori
emas, lekin eng past ham emas: qoʻshni mintaqalar koʻpincha arzonroq.

2026-yil sentabrida Steamning oʻz vitrinasidan olingan uchta haqiqiy misol:

| Oʻyin | Steam, Oʻzbekiston uchun | Bizning narx |
| --- | --- | --- |
| West Escape | $0.99 | $0.78 |
| Age of Empires IV | $27.99 | $21.20 |
| Black Myth: Wukong | $59.99 | $41.45 |

Darrov va rostini aytamiz: bu har doim ham shunday emas. Katalogdan 21 ta
tasodifiy oʻyinni tekshirdik — 17 tasi arzonroq chiqdi, 2 tasi taxminan teng,
2 tasida esa biz qimmatroq edik. Yutuqli holatlarda oʻrtacha tejash 15%
atrofida, eng kattasi 54% gacha yetdi. Shuning uchun toʻgʻri ibora — «odatda
arzonroq», «har doim» emas; narx toʻlovdan oldin koʻrinadi, oʻzingiz oʻn
soniyada solishtirasiz.

## Steam sovgʻasi, kalit emas

Buni qonuniy qiladigan mexanizm Steam sovgʻasi deb ataladi. Oʻyin u mavjud
boʻlgan mintaqada sotib olinadi va Steamning oʻz sovgʻa tizimi orqali qabul
qiluvchining akkauntiga yuboriladi — xuddi doʻstingizga tugʻilgan kunga
sovgʻa qilganingizdek.

Bundan kelib chiqadigan xulosalar:

- Hech qayerga kalit kiritish shart emas. Oʻyin kutubxonada oʻzi paydo boʻladi.
- Akkaunt paroli hech kimga kerak emas. Profilga ochiq havola yetarli.
- Oʻyin qabul qiluvchida butunlay qoladi, xuddi sotib olingan boshqasi kabi.
- Akkaunt sizniki boʻlib qolaveradi. Hech qanday «umumiy» yoki «ijaraga
  olingan» akkaunt yoʻq.

## Qanday sotib olinadi: bosqichma-bosqich

1. Katalogdan oʻyinni nomi boʻyicha toping.
2. Agar bir nechta boʻlsa, nashrni va qabul qiluvchi akkaunti mintaqasini
   tanlang.
3. Steam profiliga havolani joylashtiring. Taxallus va avatar darhol
   koʻrinadi — bu havoladagi xatodan sugʻurta.
4. Uzcard yoki Humo kartasi bilan Click, Payme yoki Uzum orqali toʻlang.
5. Sovgʻani kuting. U odatda bir soat ichida keladi.

## Asosiy xato — akkaunt mintaqasi

Sovgʻani faqat u sotib olingan mintaqada qabul qilish mumkin. Agar qabul
qiluvchining akkaunti boshqa mamlakatga tegishli boʻlsa, Steam «Qabul qilish»
tugmasini bosishga ruxsat bermaydi — buyurtma toʻxtab qolishining eng keng
tarqalgan sababi shu.

Yarim daqiqada tekshiriladi: Steam → «Akkaunt haqida» → «Mamlakat» qatori.
Buyurtma rasmiylashtirishda aynan shu mintaqani tanlash kerak. Agar mos
kelmasa, buni toʻlovdan keyin emas, oldin aniqlagan maʼqul.

## Agar oʻyin qoʻshimcha boʻlib chiqsa

DLC faqat asosiy oʻyin ustiga ishlaydi. Asosiy oʻyini yoʻq odamga qoʻshimchani
sovgʻa qilish texnik jihatdan mumkin, lekin u asosiy versiyani sotib olmaguncha
bundan hech qanday foyda boʻlmaydi. Bunday pozitsiyalar kartochkada
belgilangan, ammo baribir bir koʻz tashlagan yaxshi.

## Xavfsizlik haqida, qisqacha

Sovgʻa uchun kerak boʻlgan yagona narsa — profilga havola. U ochiq, uni
istalgan odam koʻradi.

Hech kim va hech qachon sizdan oʻyin sotib olish uchun Steam parolini, Steam
Guard kodini yoki pochtangizga kirishni soʻramasligi kerak. Agar soʻrashsa —
bu doʻkon emas, akkaunt oʻgʻirligi, va hech qanday narx bunga arzimaydi. Qoida
oddiy va istisnosi yoʻq.
""".strip()

FAQS: list[tuple[int, str, str, str]] = [
    (
        1,
        "ru",
        "Можно ли оплатить Steam узбекистанской картой?",
        "Напрямую в Steam — чаще всего нет: Uzcard и Humo за пределами страны не работают. "
        "У нас оплата идёт в сумах этими же картами через Click, Payme или Uzum, а игра "
        "приходит на аккаунт подарком Steam.",
    ),
    (
        1,
        "en",
        "Can I pay Steam with an Uzbek card?",
        "Directly on Steam, usually not: Uzcard and Humo do not work outside the country. "
        "Here you pay in sum with those same cards via Click, Payme or Uzum, and the game "
        "reaches the account as a Steam gift.",
    ),
    (
        1,
        "uz",
        "Steamga oʻzbek kartasi bilan toʻlash mumkinmi?",
        "Toʻgʻridan-toʻgʻri Steamda — koʻpincha yoʻq: Uzcard va Humo mamlakatdan tashqarida "
        "ishlamaydi. Bizda toʻlov aynan shu kartalar bilan Click, Payme yoki Uzum orqali "
        "soʻmda amalga oshadi, oʻyin esa akkauntga Steam sovgʻasi sifatida keladi.",
    ),
    (
        2,
        "ru",
        "Подарок Steam — это законно?",
        "Да. Подарок — штатная функция самого Steam: так игру дарят другу на день рождения. "
        "Аккаунт остаётся ваш, никакие правила Steam при этом не нарушаются, а игра "
        "остаётся в библиотеке навсегда.",
    ),
    (
        2,
        "en",
        "Is a Steam gift legitimate?",
        "Yes. Gifting is a built-in Steam feature — it is how you give a friend a game for "
        "their birthday. The account stays yours, no Steam rule is broken, and the game "
        "stays in the library for good.",
    ),
    (
        2,
        "uz",
        "Steam sovgʻasi qonuniymi?",
        "Ha. Sovgʻa — Steamning oʻz funksiyasi: doʻstga tugʻilgan kunga oʻyin shunday "
        "sovgʻa qilinadi. Akkaunt sizniki boʻlib qoladi, Steam qoidalari buzilmaydi, oʻyin "
        "esa kutubxonada butunlay qoladi.",
    ),
    (
        3,
        "ru",
        "Что будет, если игра уже есть у получателя?",
        "Steam не даст принять такой подарок — он останется в списке ожидающих. Поэтому "
        "перед покупкой стоит уточнить у получателя, нет ли игры в библиотеке: это "
        "единственная проверка, которую мы сделать за вас не можем.",
    ),
    (
        3,
        "en",
        "What if the recipient already owns the game?",
        "Steam will not let them accept such a gift — it stays in their pending list. So it "
        "is worth asking the recipient whether the game is already in their library: that "
        "is the one check we cannot make for you.",
    ),
    (
        3,
        "uz",
        "Agar oʻyin qabul qiluvchida allaqachon boʻlsa nima boʻladi?",
        "Steam bunday sovgʻani qabul qildirmaydi — u kutilayotganlar roʻyxatida qoladi. "
        "Shuning uchun sotib olishdan oldin qabul qiluvchidan oʻyin kutubxonasida yoʻqligini "
        "soʻrash kerak: bu biz siz uchun qila olmaydigan yagona tekshiruv.",
    ),
    (
        4,
        "ru",
        "Можно ли купить игру себе, а не в подарок?",
        "Да, и это самый частый случай. Просто укажите ссылку на свой собственный профиль "
        "Steam — подарок придёт вам, и игра встанет в вашу библиотеку.",
    ),
    (
        4,
        "en",
        "Can I buy a game for myself rather than as a gift?",
        "Yes, and that is the common case. Just give the link to your own Steam profile — "
        "the gift comes to you and the game lands in your library.",
    ),
    (
        4,
        "uz",
        "Oʻyinni sovgʻa sifatida emas, oʻzimga sotib olsam boʻladimi?",
        "Ha, va bu eng koʻp uchraydigan holat. Shunchaki oʻz Steam profilingizga havolani "
        "koʻrsating — sovgʻa sizga keladi va oʻyin kutubxonangizga tushadi.",
    ),
]


def body(markdown: str) -> str:
    """Markdown -> the exact HTML the API would have stored."""
    result = markdown_to_html(markdown)
    # Loud on loss: a dropped image or demoted heading here means the copy used
    # something the allowlist refuses, and silently shipping the remainder is
    # the failure this script exists to prevent.
    if result.dropped_images or result.unwrapped_links or result.demoted_headings:
        raise SystemExit(
            f"copy uses constructs the allowlist drops: {result.dropped_images} images, "
            f"{result.unwrapped_links} links, {result.demoted_headings} headings"
        )
    return sanitize_body(result.html, media_base_url=MEDIA_BASE, allow_empty=False)


def q(text: str) -> str:
    """Dollar-quote a literal. The copy is apostrophe-heavy in all three."""
    if "$x$" in text:
        raise SystemExit("copy contains the dollar-quote tag")
    return f"$x${text}$x$"


def main() -> None:
    rows = [
        ("ru", SLUG_RU, RU_TITLE, RU_EXCERPT, RU_BODY, RU_SEO_TITLE, RU_SEO_DESCRIPTION),
        ("en", SLUG_EN, EN_TITLE, EN_EXCERPT, EN_BODY, EN_SEO_TITLE, EN_SEO_DESCRIPTION),
        ("uz", SLUG_UZ, UZ_TITLE, UZ_EXCERPT, UZ_BODY, UZ_SEO_TITLE, UZ_SEO_DESCRIPTION),
    ]
    for locale, slug, title, excerpt, _, seo_title, seo_desc in rows:
        # The columns are length-capped; a silent truncation in Postgres would
        # cut a sentence in half on the live page.
        for name, value, cap in (
            ("slug", slug, 96),
            ("title", title, 200),
            ("excerpt", excerpt, 280),
            ("seo_title", seo_title, 200),
            ("seo_description", seo_desc, 320),
        ):
            if len(value) > cap:
                raise SystemExit(f"{locale}.{name} is {len(value)} chars, cap is {cap}")

    out = [
        "-- scripts/seed/steam_gifts_blog_post.sql",
        "--",
        "-- GENERATED by scripts/seed/build_steam_gifts_post.py — do not edit by hand.",
        "-- Edit the markdown in that script and re-run it.",
        "--",
        "-- One guide post for the `steam-gifts` brand, in ru/en/uz, with 4 FAQ entries per",
        "-- locale. The bodies were rendered through the API's own `markdown_to_html` +",
        "-- `sanitize_body`, so what lands here is byte-for-byte what an editor pasting the",
        "-- same markdown into the admin would have stored — no tag in it can be one the",
        "-- fail-closed allowlist drops on read.",
        "--",
        "-- Inserted as a DRAFT on purpose. It is editorial copy on a public site: the owner",
        "-- reads it and presses publish in the admin. `ck_blog_posts_brand_unless_draft`",
        "-- allows a draft with no brand, but this one names its brand anyway so publishing",
        "-- is the only step left.",
        "--",
        "-- Idempotent: keyed on the ru slug, rebuilt via delete-then-insert, one",
        "-- transaction. Re-running replaces the post and drops any likes/views it had",
        "-- collected (ON DELETE CASCADE) — harmless on a draft, worth knowing once it is",
        "-- published.",
        "",
        "BEGIN;",
        "",
        "DELETE FROM blog_posts WHERE id IN (",
        "    SELECT post_id FROM blog_post_translations",
        f"    WHERE locale = 'ru' AND slug = {q(SLUG_RU)}",
        ");",
        "",
        "WITH new_post AS (",
        "    INSERT INTO blog_posts (id, kind, status, primary_brand_id, show_buy_card, pin_on_brand)",
        "    SELECT gen_random_uuid(), 'guide', 'draft', b.id, true, false",
        "    FROM brands b WHERE b.slug = 'steam-gifts'",
        "    RETURNING id",
        "),",
        "tr AS (",
        "    INSERT INTO blog_post_translations "
        "(post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)",
        "    SELECT np.id, v.locale, v.slug, v.title, v.excerpt, v.body_html, "
        "v.seo_title, v.seo_description",
        "    FROM new_post np, (VALUES",
    ]

    parts = []
    for locale, slug, title, excerpt, md, seo_title, seo_desc in rows:
        parts.append(
            f"        ('{locale}', {q(slug)}, {q(title)}, {q(excerpt)},\n"
            f"         {q(body(md))},\n"
            f"         {q(seo_title)}, {q(seo_desc)})"
        )
    out.append(",\n".join(parts))
    out += [
        "    ) AS v(locale, slug, title, excerpt, body_html, seo_title, seo_description)",
        ")",
        "INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer)",
        "SELECT gen_random_uuid(), np.id, v.locale, v.sort_order, v.question, v.answer",
        "FROM new_post np, (VALUES",
    ]
    out.append(
        ",\n".join(
            f"    ({sort}, '{locale}', {q(question)},\n     {q(answer)})"
            for sort, locale, question, answer in FAQS
        )
    )
    out += [
        ") AS v(sort_order, locale, question, answer);",
        "",
        "COMMIT;",
        "",
    ]

    target = REPO / "scripts" / "seed" / "steam_gifts_blog_post.sql"
    target.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {target.relative_to(REPO)}")
    for locale, _, _, _, md, _, _ in rows:
        print(f"  {locale}: {len(body(md))} chars of html")


if __name__ == "__main__":
    main()
