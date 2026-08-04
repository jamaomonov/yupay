-- Give the Steam account field a proper localized placeholder.
--
-- The checkout account input for Steam is a *login* (alphanumeric), but with no
-- `placeholder` on the field the UI fell back to the generic "Введите ID игрока"
-- — misleading for a login. This sets required_fields[0].placeholder to a
-- login-specific string in ru/en/uz. The web form reads it via `label(...)`.
--
-- Brand-scoped + idempotent (re-running yields identical content). The value is
-- a localized object, mirroring the field's `label` shape — a plain string
-- fails the API's FormField schema (help_text/placeholder are dicts).
--
-- Apply on prod (operator psql):
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     psql -U yupay_app -d yupay -f - < scripts/seed/2026-08-05_steam_login_placeholder.sql

BEGIN;

UPDATE products p
SET required_fields = jsonb_set(
        p.required_fields, '{0,placeholder}',
        '{"ru": "Введите логин Steam", "en": "Enter your Steam login", "uz": "Steam login kiriting"}'::jsonb,
        true)
FROM brands b
WHERE b.id = p.brand_id
  AND b.slug = 'steam'
  AND jsonb_typeof(p.required_fields) = 'array'
  AND p.required_fields->0->>'key' = 'steam_login';

COMMIT;
