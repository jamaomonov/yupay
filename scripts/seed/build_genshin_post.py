"""Generate `scripts/seed/genshin_post_review.sql` — review fixes + en/uz for the
imported Genshin guide.

The Bunzy importer lands a Russian draft and nothing else. This script carries
the review edits to that draft and the two translations, rendering every body
through the API's own `markdown_to_html` + `sanitize_body` so what the seed
stores is byte-for-byte what the admin editor would have stored. See
`build_steam_gifts_post.py` for why hand-written HTML is not an option here.

Run from the repo root:

    uv run python scripts/seed/build_genshin_post.py

Regenerate and re-commit the .sql whenever the copy changes; never edit the
generated file by hand.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "apps" / "api" / "src"))

from yupay.modules.blog.markdown_html import markdown_to_html  # noqa: E402
from yupay.modules.blog.sanitize import sanitize_body  # noqa: E402

MEDIA_BASE = "https://media.yupay.uz"
POST_ID = "01a0a91f-f25d-7d60-81be-4e5926294912"
SLUG = "genshin-impact"

# --- Review fixes to the imported Russian body ------------------------------
# Applied as exact string swaps against the stored HTML so the edit is
# reviewable and the rest of the author's text is untouched. Each is a defect
# found reading the draft, not a rewrite.
RU_FIXES: list[tuple[str, str, str]] = [
    (
        "оракумы",
        "окулы",
        "Not a Genshin word. The collectibles that level the Statues of the "
        "Seven — which the same sentence already mentions — are окулы "
        "(anemoculus, geoculus and so on).",
    ),
    (
        "копите примитивные материалы",
        "копите материалы возвышения",
        "«Примитивные материалы» is nothing in the game; the advice is to hoard "
        "ascension materials, and every other term in the guide is the correct "
        "Russian one.",
    ),
    (
        "Этот genshin impact гайд для новичков объясняет",
        "Этот гайд объясняет",
        "The search phrase pasted mid-sentence in lowercase, twice. It reads as "
        "stuffing to a person and buys nothing from a search engine that has "
        "the title, the heading and the URL already.",
    ),
    (
        "Любой genshin impact гайд для новичков начинается с одного",
        "Любой гайд для новичков начинается с одного",
        "Second instance of the same phrase.",
    ),
    (
        '<a href="https://yupay.uz">Yupay</a> продаёт пополнения для игр в '
        "узбекских сумах с локальными способами оплаты",
        '<a href="https://yupay.uz/store/genshin-impact">Yupay</a> пополняет '
        "Genshin Impact по UID в узбекских сумах, картами Uzcard и Humo",
        "The one link that had to be here was missing: a Genshin guide pointed "
        "at the homepage instead of the Genshin top-up page. The article had no "
        "link into /store at all.",
    ),
]

EN_TITLE = "How to play Genshin Impact: a beginner's guide"
EN_EXCERPT = (
    "Elements and reactions matter more than character levels, the 5-star pity lands at 90 "
    "wishes, and Primogems come free if you know where to look. Everything a new Traveler needs."
)
EN_SEO_DESCRIPTION = (
    "A beginner's guide to Genshin Impact: first steps in Teyvat, how elemental reactions work, "
    "the wish and pity system explained, and how to earn Primogems without spending."
)

EN_BODY = """
## The short version

- Genshin Impact draws around 15 million monthly players as of September 2025, so a newcomer is never short of a community or advice.
- The seven elements and the reactions between them matter more than a character's level: the right pairing out-damages brute-force levelling.
- The hard pity for a 5-star character lands on the 90th wish and soft pity starts around the 74th, so it pays to save deliberately.
- Daily commissions, world exploration and the Spiral Abyss give a steady flow of Primogems for free.

Starting Genshin Impact is simple: download it, finish the tutorial in Mondstadt, and concentrate on learning the elements rather than levelling blindly. This guide covers how the game works, how characters and the banner and wish systems fit together, and how to earn Primogems without spending much.

It remains one of the most popular open-world RPGs there is. As of September 2025 it had roughly 15 million players a month ([Dexerto](https://www.dexerto.com/genshin-impact/how-many-people-play-genshin-impact-player-count-tracker-1683360/), 2025), which means there is a large community around you and whatever problem you hit, somebody has already solved it.

## Where to begin: your first steps in Teyvat

Every beginner's guide starts the same way: play the prologue and choose the Traveler's gender. That opens up the city of Mondstadt, the Anemo element and your first quests. Do not rush to close everything at once — explore the map calmly and gather resources.

Adventure Rank unlocks new systems gradually. It rises with quests, waypoints and domains. While your rank is low, hoard ascension materials and do not spend levelling resources on weak characters.

Three habits that save you days later:

- Unlock every waypoint and Statue of the Seven you come across.
- Pick the local flora — you will need it to ascend your heroes.
- Do the four daily commissions for the experience and the Primogems.

The Spiral Abyss and world bosses can wait until your team is stronger. Understanding the basics of combat comes first.

## How characters and elements work

The combat system rests on seven elements: Pyro, Hydro, Electro, Cryo, Anemo, Geo and Dendro. Each character belongs to one of them. A team's strength comes not from its levels but from how well those elements combine.

When two elements meet on one enemy, an elemental reaction fires. Hydro and Pyro give Vaporize and amplified damage. Electro and Hydro cause Electro-Charged. Cryo and Pyro give Melt. Reactions are what turn a team that looks weak on paper into a strong one.

How do you use that? Build a party of four so the elements complement each other. One deals the main damage, the second applies a second element for the reaction, the third heals or shields, the fourth buffs.

Team roles usually break down like this:

- The main DPS holds the field and attacks most.
- The sub-DPS applies the second element for reactions.
- A healer or shielder keeps the team alive.
- A buffer raises the whole group's damage.

Understanding reactions matters more than owning rare characters. A well-built team of starter heroes clears almost the entire story.

## The banner and wish system, explained

New characters and weapons come from wishes, the game's gacha system. Wishes are paid for with special items: Intertwined Fates for the character and weapon banners. The maths here is worth knowing, so you do not spend Primogems blindly.

The base rate for a 5-star hero is low, around 0.6%. But the game protects you with two mechanics. Soft pity begins around the 74th wish, where the rate climbs sharply. Hard pity triggers on the 90th wish of a character banner: a 5-star is guaranteed.

Then the 50/50 system applies. Your first guaranteed 5-star has a 50% chance of being the featured character. If you lose it and get a random one from the standard pool, the next 5-star is guaranteed to be the featured one. Worst case, the character you want costs about 180 wishes.

The practical takeaway for a beginner is simple. Do not spread single wishes across banners. Save for a specific character who will strengthen your team, and walk the counter to pity deliberately.

## Levelling up without spending

Genshin Impact is entirely free, and you can finish it without paying a thing. The main rule of economy: invest only in the heroes you actually play. Spreading experience and materials across everyone slows your progress more than anything else.

Level one main DPS to the cap of your Adventure Rank first. Ascend them on time to lift the level ceiling. Level talents on whoever deals the damage, not on the support.

Artifacts often matter more than a character's level. Do not chase perfect stats early on. Put on any set with useful bonuses and replace it as you go. Leave farming the best artifacts for the late game.

A few rules that protect your resources:

- Do not spend Original Resin on domains while your team is weak.
- Eat attack and defence food before hard fights.
- Cooking and alchemy cover a lot of needs for free.

That approach gives steady progress with no money spent. There is no hurry: the game holds hundreds of hours of content.

## How to earn Primogems quickly

Primogems are the main wish currency, and a beginner can earn them steadily and for free. The key is not to miss the regular sources and to explore actively. Played systematically, it adds up to a decent sum every month.

The main free sources:

- Daily commissions: four tasks a day for quick Primogems.
- Exploration: chests, puzzles and oculi are scattered across the map.
- Spiral Abyss: a combat challenge with a large reward each cycle.
- Events: seasonal events often hand out hundreds of Primogems over a couple of evenings.
- Achievements and mail gifts from the developers.

One more tip: open new regions. Every new territory means dozens of chests and new Statues of the Seven, which also give Primogems. Exploration stays the most underrated source of currency among beginners.

If you do decide to top up, use a convenient local service. [Yupay](https://yupay.uz/en/store/genshin-impact) tops up Genshin Impact by UID in Uzbek sum, with Uzcard and Humo cards — easier than working out foreign cards. If you play on Steam too, our guide on [topping up Steam in Uzbekistan](https://yupay.uz/en/blog/steam) will help.

Start small: today, do the four daily commissions and open one new stretch of map. After a couple of weeks of that routine you will have saved for your first deliberate run of wishes, and you will see how the system rewards patient players.
""".strip()

UZ_TITLE = "Genshin Impactda qanday oʻynash kerak: yangi boshlovchilar uchun qoʻllanma"
UZ_EXCERPT = (
    "Elementlar va ular orasidagi reaksiyalar qahramon darajasidan muhimroq, 5 yulduzli "
    "kafolat 90-duoda keladi, Boshlangʻich kristallarni esa bepul yigʻish mumkin."
)
UZ_SEO_DESCRIPTION = (
    "Genshin Impact boʻyicha yangi boshlovchilar uchun qoʻllanma: Teyvatdagi ilk qadamlar, "
    "element reaksiyalari, duo va kafolat tizimi hamda kristallarni bepul yigʻish yoʻllari."
)

UZ_BODY = """
## Eng muhimi

- 2025-yil sentabr holatiga koʻra Genshin Impactni oyiga 15 millionga yaqin odam oʻynaydi, shuning uchun yangi oʻyinchi hamjamiyat va maslahatni oson topadi.
- Yetti element va ular orasidagi reaksiyalar qahramon darajasidan muhimroq: toʻgʻri tanlangan juftlik koʻr-koʻrona darajani oshirishdan koʻra koʻproq zarar beradi.
- 5 yulduzli qahramon uchun qattiq kafolat 90-duoda ishlaydi, yumshoq kafolat esa taxminan 74-duodan boshlanadi — demak kristallarni ongli ravishda yigʻish kerak.
- Kundalik topshiriqlar, dunyoni oʻrganish va Burama Tubsizlik bepul kristallarning barqaror manbasi.

Genshin Impactni boshlash oson: oʻyinni yuklab oling, Mondshtadtdagi darsni yakunlang va koʻr-koʻrona daraja oshirish emas, elementlarni oʻrganishga eʼtibor bering. Bu qoʻllanma oʻyin qanday ishlashini, qahramonlar, banner va duo tizimi qanday bogʻlanishini hamda katta xarajatsiz Boshlangʻich kristallarni qanday olishni tushuntiradi.

Oʻyin ochiq dunyoli eng mashhur rol oʻyinlaridan biri boʻlib qolmoqda. 2025-yil sentabr holatiga koʻra unda oyiga 15 millionga yaqin odam oʻynaydi ([Dexerto](https://www.dexerto.com/genshin-impact/how-many-people-play-genshin-impact-player-count-tracker-1683360/), 2025). Bu atrofingizda katta hamjamiyat borligini va duch kelgan muammoyingizni kimdir allaqachon hal qilganini anglatadi.

## Nimadan boshlash kerak: Teyvatdagi ilk qadamlar

Har qanday qoʻllanma bir xil boshlanadi: prologni oʻtang va Sayyohning jinsini tanlang. Shundan soʻng Mondshtadt shahri, Anemo elementi va ilk kvestlar ochiladi. Hammasini birdan yopishga shoshilmang — xaritani xotirjam oʻrganing va resurs yigʻing.

Sarguzasht darajasi yangi mexanikalarni bosqichma-bosqich ochadi. U kvestlar, teleportlar va zindonlar hisobiga oʻsadi. Daraja past ekan, yuksaltirish materiallarini yigʻing va kuchsiz qahramonlarga resurs sarflamang.

Keyinchalik kunlab vaqtni tejaydigan uchta odat:

- Koʻrgan har bir teleport va Yettilik haykalini oching.
- Mahalliy oʻsimliklarni yigʻing — ular qahramonlarni yuksaltirish uchun kerak.
- Har kuni toʻrtta topshiriqni tajriba va kristallar uchun bajaring.

Burama Tubsizlik va dunyo bosslari jamoangiz kuchayguncha kutib turadi. Avval jang qoidalarini tushunish muhimroq.

## Qahramonlar va elementlar qanday ishlaydi

Jang tizimi asosida yettita element yotadi: Piro, Gidro, Elektro, Krio, Anemo, Geo va Dendro. Har bir qahramon bitta elementga tegishli. Jamoaning kuchi darajaga emas, balki bu elementlarni qanchalik oqilona birlashtirishingizga bogʻliq.

Bitta raqibda ikkita element uchrashganda element reaksiyasi ishga tushadi. Gidro va Piro Bugʻlanishni va kuchaytirilgan zararni beradi. Elektro va Gidro Zaryadlanishni chaqiradi. Krio va Piro Erishni beradi. Aynan reaksiyalar qogʻozda kuchsiz koʻringan jamoani kuchliga aylantiradi.

Buni amalda qanday qoʻllash kerak? Toʻrt qahramondan iborat jamoani elementlar bir-birini toʻldiradigan qilib yigʻing. Biri asosiy zarar beradi, ikkinchisi reaksiya uchun element qoʻyadi, uchinchisi davolaydi yoki himoya qiladi, toʻrtinchisi kuchaytiradi.

Jamoadagi rollar odatda shunday taqsimlanadi:

- Asosiy zarar beruvchi maydonda turadi va eng koʻp uradi.
- Yordamchi zarar beruvchi reaksiya uchun ikkinchi elementni qoʻyadi.
- Davolovchi yoki qalqon beruvchi jamoani tirik saqlaydi.
- Kuchaytiruvchi butun guruh zararini oshiradi.

Reaksiyalarni tushunish noyob qahramonlarga ega boʻlishdan muhimroq. Boshlangʻich qahramonlardan yaxshi yigʻilgan toʻrtlik deyarli butun syujetni oʻtadi.

## Banner va duo tizimining tahlili

Yangi qahramon va qurollar duolar orqali olinadi — bu oʻyindagi gacha tizimi. Duolar uchun maxsus buyumlar kerak: qahramon va qurol bannerlari uchun Chirmashgan taqdirlar. Kristallarni koʻr-koʻrona sarflamaslik uchun bu yerdagi matematikani bilish foydali.

5 yulduzli qahramon tushishining bazaviy ehtimoli past — taxminan 0,6%. Lekin oʻyin sizni ikkita mexanika bilan himoya qiladi. Yumshoq kafolat taxminan 74-duodan boshlanadi, oʻshanda ehtimol keskin oshadi. Qattiq kafolat qahramon bannerining 90-duosida ishlaydi: 5 yulduzli albatta tushadi.

Keyin 50/50 tizimi ishga tushadi. Kafolat bilan olingan birinchi 5 yulduzli qahramoningiz 50% ehtimol bilan aynan bannerdagi qahramon boʻladi. Omad kelmay, umumiy toʻplamdan tasodifiy qahramon tushsa, keyingi 5 yulduzli aniq bannerdagisi boʻladi. Eng yomon holatda kerakli qahramon taxminan 180 duoga tushadi.

Yangi boshlovchi uchun amaliy xulosa oddiy. Turli bannerlarda bittadan duo aylantirmang. Jamoangizni kuchaytiradigan aniq bir qahramonga yigʻing va hisoblagichni ongli ravishda kafolatgacha olib boring.

## Katta xarajatsiz daraja oshirish maslahatlari

Genshin Impact toʻliq bepul va uni bironta ham donatsiz oʻtish mumkin. Tejashning asosiy qoidasi: resurslarni faqat oʻzingiz haqiqatan oʻynaydigan qahramonlarga sarflang. Tajriba va materiallarni hammaga sochish taraqqiyotni eng koʻp sekinlashtiradi.

Avval bitta asosiy zarar beruvchini Sarguzasht darajangiz chegarasigacha koʻtaring. Daraja cheklovini olib tashlash uchun uni oʻz vaqtida yuksaltiring. Isteʼdodlarni yordamchida emas, asosiy zarar beruvchida oshiring.

Artefaktlar koʻpincha qahramon darajasidan muhimroq. Boshida mukammal xususiyatlar ortidan quvmang. Mos bonusli istalgan toʻplamni kiying va oʻtish davomida almashtiring. Eng yaxshi artefaktlarni yigʻishni keyingi bosqichga qoldiring.

Resurslarni asraydigan bir nechta qoida:

- Jamoa kuchsiz ekan, zindonlarga Boshlangʻich smolani sarflamang.
- Ogʻir janglardan oldin hujum va himoyani oshiradigan taomlarni yeng.
- Pazandalik va alkimyo koʻp ehtiyojni bepul qoplaydi.

Bunday yondashuv pul sarflamasdan bir tekis taraqqiyot beradi. Shoshilishga hojat yoʻq: oʻyinda yuzlab soatlik kontent bor.

## Kristallarni qanday tez olish mumkin

Boshlangʻich kristallar — duolar uchun asosiy valyuta va yangi oʻyinchi ularni barqaror hamda bepul olishi mumkin. Kalit shundaki, muntazam manbalarni oʻtkazib yubormaslik va dunyoni faol oʻrganish kerak. Tizimli oʻynaganda har oyda anchagina summa toʻplanadi.

Kristallarning asosiy bepul manbalari:

- Kundalik topshiriqlar: kuniga toʻrtta vazifa tez kristal beradi.
- Dunyoni oʻrganish: sandiqlar, boshqotirmalar va okullar butun xarita boʻylab sochilgan.
- Burama Tubsizlik: har siklda katta mukofotli jangovar sinov.
- Tadbirlar: mavsumiy tadbirlar koʻpincha bir necha kechada yuzlab kristal beradi.
- Yutuqlar va ishlab chiquvchilardan pochta sovgʻalari.

Alohida maslahat: yangi hududlarni oching. Har bir yangi hudud — oʻnlab sandiq va yangi Yettilik haykallari, ular ham kristal beradi. Dunyoni oʻrganish yangi oʻyinchilar orasida eng kam baholanadigan valyuta manbasi boʻlib qolmoqda.

Agar baribir hisobni toʻldirishga qaror qilsangiz, qulay mahalliy xizmatdan foydalaning. Masalan, [Yupay](https://yupay.uz/uz/store/genshin-impact) Genshin Impactni UID boʻyicha oʻzbek soʻmida, Uzcard va Humo kartalari bilan toʻldiradi — chet el kartalari bilan boshni qotirishdan qulayroq. Steamda ham oʻynaydiganlarga [Oʻzbekistonda Steamni qanday toʻldirish](https://yupay.uz/uz/blog/steam) boʻyicha qoʻllanmamiz asqotadi.

Kichikdan boshlang: bugun toʻrtta kundalik topshiriqni bajaring va xaritaning bitta yangi qismini oching. Bir necha haftalik shunday tartibdan soʻng birinchi ongli duolar seriyasiga yigʻasiz va tizim sabrli oʻyinchilarni qanday mukofotlashini koʻrasiz.
""".strip()

#: The four questions the importer wrote in Russian, translated. Order and
#: `sort_order` match the Russian rows so the three locales answer the same
#: questions in the same order.
FAQS: list[tuple[int, str, str, str]] = [
    (
        0,
        "en",
        "How many wishes guarantee a 5-star character?",
        "Hard pity triggers on the 90th wish of a character banner — a 5-star is guaranteed "
        "there. Soft pity starts around the 74th, where the rate climbs sharply, so most "
        "5-stars arrive before 90. With a lost 50/50 the featured character costs about 180 "
        "wishes at worst.",
    ),
    (
        0,
        "uz",
        "Kafolatlangan 5 yulduzli qahramon uchun nechta duo kerak?",
        "Qattiq kafolat qahramon bannerining 90-duosida ishlaydi — u yerda 5 yulduzli albatta "
        "tushadi. Yumshoq kafolat taxminan 74-duodan boshlanadi va ehtimol keskin oshadi, "
        "shuning uchun koʻpchilik 5 yulduzlilar 90 gacha keladi. 50/50 yutqazilganda kerakli "
        "qahramon eng yomon holatda taxminan 180 duoga tushadi.",
    ),
    (
        1,
        "en",
        "Is Genshin Impact free?",
        "Yes, completely. The story, the open world and the events are all available without "
        "paying, and you can finish the game without spending. Wishes for new characters are "
        "what money buys, and Primogems for those can be earned in-game.",
    ),
    (
        1,
        "uz",
        "Genshin Impact bepulmi?",
        "Ha, toʻliq bepul. Syujet, ochiq dunyo va tadbirlar toʻlovsiz ochiq, oʻyinni pul "
        "sarflamasdan oxirigacha oʻtish mumkin. Pulga yangi qahramonlar uchun duolar olinadi, "
        "ular uchun kerakli kristallarni esa oʻyin ichida yigʻsa boʻladi.",
    ),
    (
        2,
        "en",
        "How does a beginner save Primogems quickly?",
        "Do the four daily commissions every day, explore new regions for chests and oculi, "
        "and clear the Spiral Abyss each cycle. Seasonal events add hundreds over a couple of "
        "evenings. Played steadily, that is a meaningful sum every month with nothing spent.",
    ),
    (
        2,
        "uz",
        "Yangi oʻyinchi kristallarni qanday tez yigʻadi?",
        "Har kuni toʻrtta kundalik topshiriqni bajaring, sandiq va okullar uchun yangi "
        "hududlarni oching, har siklda Burama Tubsizlikni yeching. Mavsumiy tadbirlar bir "
        "necha kechada yuzlab kristal qoʻshadi. Muntazam oʻynaganda bu hech narsa "
        "sarflamasdan har oyda sezilarli summa.",
    ),
    (
        3,
        "en",
        "What is the 50/50 system in wishes?",
        "Your first guaranteed 5-star has a 50% chance of being the banner's featured "
        "character. Lose that coin flip and you get a random 5-star from the standard pool — "
        "but then the next one is guaranteed to be the featured character.",
    ),
    (
        3,
        "uz",
        "Duolardagi 50/50 tizimi nima?",
        "Kafolat bilan olingan birinchi 5 yulduzlingiz 50% ehtimol bilan bannerdagi qahramon "
        "boʻladi. Bu tanga tashlashda yutqazsangiz, umumiy toʻplamdan tasodifiy 5 yulduzli "
        "tushadi — lekin keyingisi aniq bannerdagi qahramon boʻlishi kafolatlanadi.",
    ),
]


def body(markdown: str) -> str:
    result = markdown_to_html(markdown)
    if result.dropped_images or result.unwrapped_links or result.demoted_headings:
        raise SystemExit(
            f"copy uses constructs the allowlist drops: {result.dropped_images} images, "
            f"{result.unwrapped_links} links, {result.demoted_headings} headings"
        )
    return sanitize_body(result.html, media_base_url=MEDIA_BASE, allow_empty=False)


def q(text: str) -> str:
    if "$x$" in text:
        raise SystemExit("copy contains the dollar-quote tag")
    return f"$x${text}$x$"


def main() -> None:
    rows = [
        ("en", EN_TITLE, EN_EXCERPT, EN_BODY, EN_SEO_DESCRIPTION),
        ("uz", UZ_TITLE, UZ_EXCERPT, UZ_BODY, UZ_SEO_DESCRIPTION),
    ]
    for locale, title, excerpt, _, seo_desc in rows:
        for name, value, cap in (
            ("title", title, 200),
            ("excerpt", excerpt, 280),
            ("seo_description", seo_desc, 320),
        ):
            if len(value) > cap:
                raise SystemExit(f"{locale}.{name} is {len(value)} chars, cap is {cap}")

    out = [
        "-- scripts/seed/genshin_post_review.sql",
        "--",
        "-- GENERATED by scripts/seed/build_genshin_post.py — do not edit by hand.",
        "--",
        "-- Review fixes to the imported Russian Genshin draft, plus en/uz translations.",
        "-- The importer lands Russian only and leaves the brand unset; both are dealt",
        "-- with here.",
        "--",
        "-- The Russian body is patched with exact string swaps rather than replaced, so",
        "-- the diff is the five defects the review found and nothing else. Each swap",
        "-- asserts it changed something: a silent no-op would mean the draft moved under",
        "-- us and the fix never landed.",
        "--",
        "-- The two new bodies went through the API's own markdown_to_html +",
        "-- sanitize_body, so no tag in them can be one the fail-closed allowlist drops.",
        "--",
        "-- Stays a DRAFT. Publishing is the owner's call in the admin.",
        "",
        "BEGIN;",
        "",
        "-- 1. The brand. `ck_blog_posts_brand_unless_draft` lets a draft carry none,",
        "-- which is why the importer's row was legal — and why publishing would have",
        "-- failed on it. It is a Genshin guide; the brand is genshin-impact.",
        "UPDATE blog_posts SET primary_brand_id = (SELECT id FROM brands WHERE slug = 'genshin-impact')",
        f"WHERE id = '{POST_ID}';",
        "",
        "-- 2. Review fixes to the Russian body.",
    ]

    for needle, replacement, why in RU_FIXES:
        # Applied when the old text is there, skipped when the new text already
        # is — so a re-run is a no-op rather than a failure. It still raises
        # when neither is present, which is the case that matters: the draft
        # changed under us and this fix is silently not being applied.
        out += [
            f"-- {why}",
            "DO $do$",
            "BEGIN",
            "    IF EXISTS (",
            "        SELECT 1 FROM blog_post_translations",
            f"        WHERE post_id = '{POST_ID}' AND locale = 'ru'",
            f"          AND position({q(needle)} in body_html) > 0",
            "    ) THEN",
            "        UPDATE blog_post_translations",
            f"        SET body_html = replace(body_html, {q(needle)}, {q(replacement)})",
            f"        WHERE post_id = '{POST_ID}' AND locale = 'ru';",
            "    ELSIF NOT EXISTS (",
            "        SELECT 1 FROM blog_post_translations",
            f"        WHERE post_id = '{POST_ID}' AND locale = 'ru'",
            f"          AND position({q(replacement)} in body_html) > 0",
            "    ) THEN",
            "        RAISE EXCEPTION",
            "            'neither the original nor the fix is present — the draft changed: %',",
            f"            {q(needle[:60])};",
            "    END IF;",
            "END",
            "$do$;",
            "",
        ]

    out += [
        "-- 3. The translations. Delete-then-insert so a re-run replaces them.",
        f"DELETE FROM blog_post_translations WHERE post_id = '{POST_ID}' AND locale IN ('en','uz');",
        "INSERT INTO blog_post_translations "
        "(post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)",
        "VALUES",
    ]
    out.append(
        ",\n".join(
            f"    ('{POST_ID}', '{locale}', {q(SLUG)}, {q(title)}, {q(excerpt)},\n"
            f"     {q(body(md))},\n"
            f"     {q(title)}, {q(seo_desc)})"
            for locale, title, excerpt, md, seo_desc in rows
        )
        + ";"
    )

    out += [
        "",
        "-- 4. The same four questions, in the same order as the Russian rows.",
        f"DELETE FROM blog_post_faqs WHERE post_id = '{POST_ID}' AND locale IN ('en','uz');",
        "INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer)",
        "VALUES",
    ]
    out.append(
        ",\n".join(
            f"    (gen_random_uuid(), '{POST_ID}', '{locale}', {sort}, {q(question)},\n"
            f"     {q(answer)})"
            for sort, locale, question, answer in FAQS
        )
        + ";"
    )
    out += ["", "COMMIT;", ""]

    target = REPO / "scripts" / "seed" / "genshin_post_review.sql"
    target.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {target.relative_to(REPO)}")
    for locale, _, _, md, _ in rows:
        print(f"  {locale}: {len(body(md))} chars of html")


if __name__ == "__main__":
    main()
