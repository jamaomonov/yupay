-- Turn on storefront verification for the Telegram username field.
--
-- Pure configuration: `FormField.check` is what opts a field into
-- `POST /catalog/brands/{slug}/check-player`, which already exists and is
-- already one of §10's four named advisory lookups. No new endpoint, and no
-- fifth entry in that list — two more brands reach the same one.
--
-- G2B answers for a Telegram username under its `Telegram` game: confirmed
-- 2026-09-20 against a real handle, which came back
-- `{"valid": "valid", "name": "Jam", "img_src": ...}`, and against a nonsense
-- one, which came back `{"valid": "invalid"}`. Both `@name` and `name` work,
-- which is what the field's existing pattern already allows.
--
-- NOVA is deliberately not a fallback here, unlike every other checked brand:
-- it has no Telegram validation at all. Its Fragment `quote` takes a username
-- and ignores it — it priced one that does not exist and echoed it back — so
-- there is nothing to fall back to. A G2B outage means this field goes
-- unchecked, which is the pre-existing behaviour and not a regression; it is
-- recorded in ADR-0085 rather than left to be discovered.
--
-- `telegram-premium` resolves its game code from its own G2B mapping;
-- `telegram-stars` from `player_check.G2B_VALIDATE_ONLY`, because G2B sells
-- Stars only in fixed packs and is not a channel for the free-amount line.

BEGIN;

UPDATE products p
SET required_fields = (
        SELECT jsonb_agg(
            CASE
                WHEN f->>'key' = 'username'
                THEN jsonb_set(f, '{check}', '{"provider":"g2b","server_field":null}'::jsonb)
                ELSE f
            END
            ORDER BY ord
        )
        FROM jsonb_array_elements(p.required_fields) WITH ORDINALITY AS t(f, ord)
    ),
    updated_at = CURRENT_TIMESTAMP
FROM brands b
WHERE b.id = p.brand_id
  AND b.slug IN ('telegram-stars', 'telegram-premium');

SELECT b.slug, p.slug AS product, f->>'key' AS field, f->'check' AS check
FROM products p
JOIN brands b ON b.id = p.brand_id
CROSS JOIN LATERAL jsonb_array_elements(p.required_fields) f
WHERE b.slug IN ('telegram-stars', 'telegram-premium');

COMMIT;
