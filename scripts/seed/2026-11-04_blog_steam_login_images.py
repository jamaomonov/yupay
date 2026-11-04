"""Blog «Как пополнить Steam в Узбекистане»: the «где взять логин» paragraph.

Rewrites the paragraph to the dropdown/app wording and puts the two
screenshots uploaded by ``2026-11-04_steam_login_help.py`` under it (same
images as the field hint). Bodies are validated with the blog's own
``sanitize_body`` before the write. Run inside the prod api container;
``APPLY=1`` writes, otherwise prints the new paragraph. Idempotent: a body
that no longer contains the old paragraph is left alone.
"""

from __future__ import annotations

import asyncio
import os

import yupay.main  # noqa: F401 -- registers every model
from sqlalchemy import text
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.modules.blog.sanitize import sanitize_body

POST_ID = "01a0a530-c17f-7392-a0fd-c3cfd430a181"
DESKTOP = "https://cdn.yupay.uz/field_help_image/2026/11/01a1a640-109d-7983-9283-a2f5ec8fe4ff.webp"
PHONE = "https://cdn.yupay.uz/field_help_image/2026/11/01a1a640-12c0-78f2-bdb3-b7af851fa99e.webp"

OLD = {
    "ru": "<p>Где взять логин: откройте приложение Steam или сайт store.steampowered.com,"
    " нажмите на имя профиля в правом верхнем углу и перейдите в раздел «Об аккаунте»."
    " Логин указан вверху. Это именно логин, а не отображаемое имя профиля.</p>",
    "en": "<p>Where to find the login: open the Steam app or store.steampowered.com, click"
    " your profile name in the top-right corner and go to Account details. The login is"
    " shown at the top. That is the login, not your display name.</p>",
    "uz": "<p>Login ni qayerdan olish: Steam ilovasini yoki store.steampowered.com saytini"
    " oching, yuqori oʻng burchakdagi profil nomini bosing va «Hisob haqida» boʻlimiga"
    " oʻting. Login yuqorida koʻrsatilgan. Bu aynan login, koʻrsatiladigan profil nomi"
    " emas.</p>",
}

NEW = {
    "ru": (
        "<p>Где взять логин: на компьютере нажмите на своё имя справа вверху — логин написан"
        " рядом с «Об аккаунте», заходить на страницу аккаунта не нужно. В приложении Steam"
        " откройте меню профиля — логин стоит под «Сменить аккаунт». Это именно логин,"
        " а не отображаемое имя профиля.</p>",
        "Логин Steam на компьютере: меню под именем, строка «Об аккаунте»",
        "Логин Steam в приложении: под пунктом «Сменить аккаунт»",
    ),
    "en": (
        "<p>Where to find the login: on a computer, click your name in the top-right corner —"
        " the login is printed next to “Account details”, no need to open the account page."
        " In the Steam app, open the profile menu — the login is under “Change account”."
        " That is the login, not your display name.</p>",
        "Steam login on a computer: the menu under your name, next to Account details",
        "Steam login in the app: under Change account",
    ),
    "uz": (
        "<p>Login ni qayerdan olish: kompyuterda oʻng yuqoridagi ismingizni bosing — login"
        " «Об аккаунте» (Account details) yonida yozilgan, hisob sahifasiga kirish shart emas."
        " Steam ilovasida profil menyusini oching — login «Сменить аккаунт» (Change account)"
        " ostida turadi. Bu aynan login, koʻrsatiladigan profil nomi emas.</p>",
        "Kompyuterda Steam login: ism ostidagi menyu, «Об аккаунте» qatori",
        "Ilovada Steam login: «Сменить аккаунт» bandi ostida",
    ),
}


async def main() -> None:
    apply = os.environ.get("APPLY") == "1"
    media = get_settings().r2_public_base_url
    async with get_session_factory()() as db:
        for locale, old in OLD.items():
            body = (
                await db.execute(
                    text(
                        "select body_html from blog_post_translations"
                        " where post_id = :p and locale = :l"
                    ),
                    {"p": POST_ID, "l": locale},
                )
            ).scalar_one()
            if old not in body:
                print(locale, "old paragraph not found — skipped")
                continue
            para, alt_desktop, alt_phone = NEW[locale]
            block = (
                f'{para}<img src="{DESKTOP}" alt="{alt_desktop}">'
                f'<img src="{PHONE}" alt="{alt_phone}">'
            )
            new_body = sanitize_body(body.replace(old, block), media_base_url=media)
            print(locale, "ok" if apply else "dry run", len(body), "->", len(new_body))
            if apply:
                await db.execute(
                    text(
                        "update blog_post_translations set body_html = :b"
                        " where post_id = :p and locale = :l"
                    ),
                    {"b": new_body, "p": POST_ID, "l": locale},
                )
        if apply:
            await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
