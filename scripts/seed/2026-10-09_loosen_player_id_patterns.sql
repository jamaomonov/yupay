-- Loosen every player-ID pattern: no "digits only", no tight length caps.
--
-- 2026-10-09: a Bigo customer typed `Lexus0011` and «Проверить» stayed disabled.
-- The field said `^[0-9]{5,20}$`; the live G2B check answers that id as valid.
-- Earlier the owner hit the same wall on Delta Force: ids up to 30 characters
-- against a 25-character cap. The storefront disables the button and the API
-- refuses the order on a pattern miss (`orders/validation.py`), so every such
-- miss is a lost sale with no log line to show it.
--
-- Owner decision 2026-10-09: no format restrictions on player ids anywhere.
-- What stays a guard is the supplier: a real typo fails the player check, or the
-- supplier refuses the delivery and the order is refunded. The pattern's only
-- job now is to keep junk (spaces, URLs, emoji) out of a supplier request.
--
--   player_id  ->  ^[A-Za-z0-9._#-]{1,64}$
--   server     ->  ^[0-9]{1,10}$           (MLBB / MCGG zone ids are numbers)
--
-- Untouched on purpose, because each is the platform's own rule or a structure
-- the code parses: Telegram username, Steam login, Steam invite URL, CS2 trade
-- link and skin slug.
--
-- Applies to every product, active or not, so a reactivated product does not
-- bring the old cap back. Idempotent. Aborts if anything tight is left.
--
-- Apply on prod (operator psql):
--   docker exec -i yupay-prod-postgres-1 psql -v ON_ERROR_STOP=1 \
--     -U yupay_app -d yupay < scripts/seed/2026-10-09_loosen_player_id_patterns.sql

BEGIN;

CREATE TEMP TABLE _before ON COMMIT DROP AS
SELECT p.slug, f->>'key' AS key, f->>'pattern' AS pattern
FROM products p, jsonb_array_elements(p.required_fields) f
WHERE f->>'key' IN ('player_id', 'server') AND f->>'pattern' IS NOT NULL;

UPDATE products p
SET required_fields = (
        SELECT jsonb_agg(
                   CASE
                       WHEN elem->>'key' = 'player_id' AND elem->>'pattern' IS NOT NULL THEN
                           elem || jsonb_build_object('pattern', '^[A-Za-z0-9._#-]{1,64}$')
                       WHEN elem->>'key' = 'server' AND elem->>'pattern' IS NOT NULL THEN
                           elem || jsonb_build_object('pattern', '^[0-9]{1,10}$')
                       ELSE elem
                   END
                   ORDER BY ord)
        FROM jsonb_array_elements(p.required_fields) WITH ORDINALITY AS t(elem, ord)
    )
WHERE EXISTS (
    SELECT 1 FROM jsonb_array_elements(p.required_fields) f
    WHERE f->>'key' IN ('player_id', 'server') AND f->>'pattern' IS NOT NULL
);

-- What changed, for the operator's terminal.
SELECT b.pattern AS was, count(*) AS fields, string_agg(b.slug || ':' || b.key, ', ' ORDER BY b.slug) AS products
FROM _before b
GROUP BY b.pattern
ORDER BY count(*) DESC;

DO $$
DECLARE
    left_over int;
BEGIN
    SELECT count(*) INTO left_over
    FROM products p, jsonb_array_elements(p.required_fields) f
    WHERE (f->>'key' = 'player_id' AND f->>'pattern' IS DISTINCT FROM '^[A-Za-z0-9._#-]{1,64}$'
           AND f->>'pattern' IS NOT NULL)
       OR (f->>'key' = 'server' AND f->>'pattern' IS DISTINCT FROM '^[0-9]{1,10}$'
           AND f->>'pattern' IS NOT NULL);
    IF left_over > 0 THEN
        RAISE EXCEPTION '% player_id/server fields still carry an old pattern', left_over;
    END IF;
    IF 'Lexus0011' !~ '^[A-Za-z0-9._#-]{1,64}$'
       OR repeat('9', 30) !~ '^[A-Za-z0-9._#-]{1,64}$'
       OR 'Name#1234' !~ '^[A-Za-z0-9._#-]{1,64}$' THEN
        RAISE EXCEPTION 'new pattern rejects a real id';
    END IF;
END $$;

COMMIT;
