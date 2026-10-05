"""Content for the five Bunzy drafts reviewed on 2026-10-05 — one module per post.

Each module exposes ``POST``: the post id, brand slug, cover URL, per-locale
slug / title / excerpt / seo_description / Markdown body, and the FAQ rows.
``build_bunzy_2026_10_05.py`` renders the bodies through the API's own
``markdown_to_html`` + ``sanitize_body`` and writes one SQL file per post.
"""
