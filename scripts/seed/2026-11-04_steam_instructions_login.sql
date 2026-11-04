-- Steam brand page, «Как пополнить»: the «где найти логин» paragraph.
--
-- The login is printed in the dropdown under the user's name on desktop
-- («Об аккаунте: <login>») and under «Сменить аккаунт» in the Steam app;
-- the old text sent people to the account page. Same wording as the field
-- hint (2026-11-04_steam_login_help.py). Only the last paragraph changes;
-- the steps above it are untouched. Idempotent.

BEGIN;

UPDATE brand_translations bt SET instructions =
  regexp_replace(bt.instructions, E'\n\n[^\n]*$', E'\n\n' || v.para)
FROM brands b, (VALUES
  ('ru', $p$Где найти логин Steam: на компьютере нажмите на своё имя справа вверху — логин написан рядом с «Об аккаунте». В приложении Steam: меню профиля → логин под «Сменить аккаунт». Это именно логин (имя для входа), а не отображаемое имя. Пароль не нужен. Поддерживаемые регионы: СНГ (РФ, Беларусь, Казахстан, Узбекистан).$p$),
  ('en', $p$Where to find your Steam login: on a computer, click your name in the top-right corner — the login is next to “Account details”. In the Steam app: profile menu → the login is under “Change account”. This is the login (account name), not your display name. No password needed. Supported regions: CIS (Russia, Belarus, Kazakhstan, Uzbekistan).$p$),
  ('uz', $p$Steam login ni qayerdan topish: kompyuterda oʻng yuqoridagi ismingizni bosing — login «Об аккаунте» (Account details) yonida yozilgan. Steam ilovasida: profil menyusi → login «Сменить аккаунт» (Change account) ostida. Bu aynan login (hisob nomi), koʻrsatiladigan nom emas. Parol kerak emas. Qoʻllab-quvvatlanadigan mintaqalar: MDH (Rossiya, Belarus, Qozogʻiston, Oʻzbekiston).$p$)
) AS v(locale, para)
WHERE b.slug = 'steam' AND bt.brand_id = b.id AND bt.locale = v.locale;

COMMIT;
