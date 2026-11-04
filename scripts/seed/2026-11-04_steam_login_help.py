"""Steam login field: shorter «где найти логин» text + two annotated screenshots.

The old help sent buyers to the «Об аккаунте» page. They do not need to go
there: on a computer the login is printed right in the dropdown under their
name («Об аккаунте: <login>»), and in the Steam app it sits under «Сменить
аккаунт». The screenshots come from the owner (login replaced with
``_yupay_01``, nickname «Ivan», avatar blurred — no personal data), shared
with csmarket on 2026-11-04.

Run inside the prod api container with the two webp files next to it::

    python /tmp/2026-11-04_steam_login_help.py /tmp/yupay-desktop.webp /tmp/yupay-phone.webp

``APPLY=1`` uploads to the media bucket and writes; without it the script
prints the new field and touches nothing. Re-running with ``APPLY=1`` uploads
fresh copies and overwrites the field — harmless, the old objects just stay.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import yupay.main  # noqa: F401 -- registers every model
from sqlalchemy import text
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.modules.catalog.schemas import FormField
from yupay.modules.storage.client import get_s3_client
from yupay.modules.storage.service import _build_key

HELP_TEXT = {
    "ru": (
        "На компьютере: нажмите на своё имя справа вверху — логин написан рядом"
        " с «Об аккаунте».\n"
        "В приложении Steam: меню профиля → логин под «Сменить аккаунт».\n"
        "Пароль не нужен."
    ),
    "en": (
        "On a computer: click your name in the top-right corner — the login is"
        " next to “Account details”.\n"
        "In the Steam app: profile menu → the login is under “Change account”.\n"
        "No password needed."
    ),
    "uz": (
        "Kompyuterda: oʻng yuqoridagi ismingizni bosing — login «Об аккаунте»"
        " (Account details) yonida yozilgan.\n"
        "Steam ilovasida: profil menyusi → login «Сменить аккаунт» (Change"
        " account) ostida.\n"
        "Parol kerak emas."
    ),
}
CAPTIONS = [
    {"ru": "На компьютере", "en": "On a computer", "uz": "Kompyuterda"},
    {"ru": "В приложении Steam", "en": "In the Steam app", "uz": "Steam ilovasida"},
]


def _upload(paths: list[str]) -> list[str]:
    settings = get_settings()
    client = get_s3_client()
    base = settings.r2_public_base_url.rstrip("/")
    urls: list[str] = []
    for path in paths:
        key = _build_key("field_help_image", "image/webp")
        with Path(path).open("rb") as fh:
            client.put_object(
                Bucket=settings.r2_bucket_media,
                Key=key,
                Body=fh.read(),
                ContentType="image/webp",
                CacheControl="public, max-age=31536000, immutable",
            )
        urls.append(f"{base}/{key}")
    return urls


async def main(paths: list[str]) -> None:
    apply = os.environ.get("APPLY") == "1"
    urls = _upload(paths) if apply else [f"<upload of {p}>" for p in paths]
    async with get_session_factory()() as db:
        row = (
            await db.execute(
                text(
                    "select p.id, p.required_fields from products p"
                    " join brands b on b.id = p.brand_id"
                    " where b.slug = 'steam' and p.slug = 'steam-wallet'"
                )
            )
        ).one()
        fields: list[dict[str, Any]] = list(row.required_fields)
        field = next(f for f in fields if f["key"] == "steam_login")
        field["help_text"] = HELP_TEXT
        field["help_images"] = [
            {"url": u, "caption": c} for u, c in zip(urls, CAPTIONS, strict=True)
        ]
        if apply:
            FormField.model_validate(field)  # own-bucket check on the urls
            await db.execute(
                text("update products set required_fields = cast(:f as jsonb) where id = :id"),
                {"f": json.dumps(fields, ensure_ascii=False), "id": row.id},
            )
            await db.commit()
        print(("APPLIED" if apply else "DRY RUN"), json.dumps(field, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: script.py <desktop.webp> <phone.webp>")
    asyncio.run(main(sys.argv[1:]))
