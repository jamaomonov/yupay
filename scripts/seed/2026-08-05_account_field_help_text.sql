-- "Где найти" help text for the checkout account field, per brand.
--
-- Powers the "где найти" modal (WhereToFindModal) on the brand checkout: the
-- info button only renders when required_fields[0].help_text is present. Content
-- is real, sourced from how each game/app actually surfaces the account
-- identifier (see the PR/commit notes) — not invented.
--
-- Shape: help_text is a localized object {ru,en,uz}, mirroring the field's
-- `label` (a plain string fails the API's FormField schema). Brand-scoped and
-- idempotent — re-running yields identical content. The `->0->>'key'` guard
-- ensures we only touch the expected identifier field.
--
-- Apply on prod (operator psql):
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     psql -U yupay_app -d yupay -f - < scripts/seed/2026-08-05_account_field_help_text.sql

BEGIN;

-- PUBG Mobile — Character ID (8–10 digit number) under the nickname.
UPDATE products p
SET required_fields = jsonb_set(p.required_fields, '{0,help_text}',
  '{"ru":"Откройте PUBG Mobile и нажмите на аватар в левом верхнем углу лобби.\nВ профиле под ником указан Character ID — число из 8–10 цифр.\nНажмите значок копирования рядом с ID, чтобы скопировать без ошибок.\nПароль не нужен — пополнение идёт по публичному ID.","en":"Open PUBG Mobile and tap your avatar in the top-left corner of the lobby.\nIn your profile, the Character ID — an 8–10 digit number — is shown under your nickname.\nTap the copy icon next to the ID to copy it exactly.\nNo password needed — top-up is by public ID.","uz":"PUBG Mobile ni oching va lobbi chap yuqori burchagidagi avatarni bosing.\nProfilda taxallus ostida Character ID — 8–10 raqamli son — koʻrsatiladi.\nXatosiz nusxalash uchun ID yonidagi nusxa belgisini bosing.\nParol kerak emas — toʻldirish ommaviy ID orqali."}'::jsonb, true)
FROM brands b
WHERE b.id = p.brand_id AND b.slug = 'pubg-mobile'
  AND jsonb_typeof(p.required_fields) = 'array'
  AND p.required_fields->0->>'key' = 'player_id';

-- Delta Force — UID next to the nickname on the profile page.
UPDATE products p
SET required_fields = jsonb_set(p.required_fields, '{0,help_text}',
  '{"ru":"Откройте Delta Force и нажмите на иконку профиля (аватар).\nНа странице профиля рядом с ником показан «ID» — длинный номер (UID).\nСкопируйте номер полностью.\nПароль передавать не нужно.","en":"Open Delta Force and tap the profile icon (avatar).\nOn the profile page, next to your nickname, you will see the ID — a long number (UID).\nCopy the number in full.\nNo password required.","uz":"Delta Force ni oching va profil belgisini (avatar) bosing.\nProfil sahifasida taxallus yonida ID — uzun raqam (UID) koʻrsatiladi.\nRaqamni toʻliq nusxalang.\nParol kerak emas."}'::jsonb, true)
FROM brands b
WHERE b.id = p.brand_id AND b.slug = 'delta-force'
  AND jsonb_typeof(p.required_fields) = 'array'
  AND p.required_fields->0->>'key' = 'player_id';

-- Arena Breakout (mobile) — numeric Player ID (UID) under the nickname.
UPDATE products p
SET required_fields = jsonb_set(p.required_fields, '{0,help_text}',
  '{"ru":"Откройте Arena Breakout и нажмите на аватар в левом верхнем углу.\nВ разделе профиля под ником указан «ID» — числовой Player ID (UID).\nСкопируйте номер полностью, без букв и символов.\nПароль передавать не нужно.","en":"Open Arena Breakout and tap your avatar in the top-left corner.\nIn the profile section, under your nickname, the ID — a numeric Player ID (UID) — is shown.\nCopy the number in full, without letters or symbols.\nNo password required.","uz":"Arena Breakout ni oching va chap yuqori burchakdagi avatarni bosing.\nProfil boʻlimida taxallus ostida ID — raqamli Player ID (UID) koʻrsatiladi.\nRaqamni harflar va belgilarsiz toʻliq nusxalang.\nParol kerak emas."}'::jsonb, true)
FROM brands b
WHERE b.id = p.brand_id AND b.slug = 'arena-breakout'
  AND jsonb_typeof(p.required_fields) = 'array'
  AND p.required_fields->0->>'key' = 'player_id';

-- Arena Breakout: Infinite (PC) — Player ID (UID) of the PC account.
UPDATE products p
SET required_fields = jsonb_set(p.required_fields, '{0,help_text}',
  '{"ru":"Запустите Arena Breakout: Infinite на ПК и откройте профиль (кнопка в правом верхнем углу).\nНа странице профиля показан ваш Player ID (UID) — скопируйте его.\nУбедитесь, что это ID именно ПК-аккаунта, а не мобильного.\nПароль передавать не нужно.","en":"Launch Arena Breakout: Infinite on PC and open your profile (button in the top-right corner).\nYour Player ID (UID) is shown on the profile page — copy it.\nMake sure it is your PC account ID, not a mobile one.\nNo password required.","uz":"Arena Breakout: Infinite ni PC da ishga tushiring va profilni oching (oʻng yuqori burchakdagi tugma).\nProfil sahifasida Player ID (UID) koʻrsatiladi — uni nusxalang.\nBu mobil emas, balki PC hisobingiz IDsi ekaniga ishonch hosil qiling.\nParol kerak emas."}'::jsonb, true)
FROM brands b
WHERE b.id = p.brand_id AND b.slug = 'arena-breakout-infinite'
  AND jsonb_typeof(p.required_fields) = 'array'
  AND p.required_fields->0->>'key' = 'player_id';

-- Steam — the account name (login) under Account details.
UPDATE products p
SET required_fields = jsonb_set(p.required_fields, '{0,help_text}',
  '{"ru":"Откройте приложение Steam или сайт store.steampowered.com и войдите в аккаунт.\nНажмите на имя профиля в правом верхнем углу и откройте «Об аккаунте».\nВверху указан ваш логин (имя аккаунта) — он нужен для пополнения.\nПароль передавать не нужно.","en":"Open the Steam app or store.steampowered.com and sign in.\nClick your profile name in the top-right corner and open Account details.\nYour login (account name) is shown at the top.\nNo password required.","uz":"Steam ilovasini yoki store.steampowered.com saytini oching va hisobga kiring.\nOʻng yuqori burchakdagi profil nomini bosing va Hisob haqida boʻlimini oching.\nYuqorida logingiz (hisob nomi) koʻrsatiladi — u toʻldirish uchun kerak.\nParol kerak emas."}'::jsonb, true)
FROM brands b
WHERE b.id = p.brand_id AND b.slug = 'steam'
  AND jsonb_typeof(p.required_fields) = 'array'
  AND p.required_fields->0->>'key' = 'steam_login';

COMMIT;
