# Runbook — Bootstrap the first admin

The admin SPA at `admin.localhost` (dev) / `admin.yupay.io` (prod) uses Telegram
login + the `admin` role on `users.roles`. The first admin needs to be promoted
by hand because no UI exists yet to grant roles.

## Procedure

1. Open the admin SPA in your browser.
2. Click the Telegram Login Widget. Authorise the bot. The backend creates a
   `users` row and a `telegram_links` row, then mints a JWT.
3. The SPA renders a 403 page because the user has no `admin` role yet.
4. Find the Telegram id (it's the `tg_id` claim in the JWT, or look it up in
   Postgres):

   ```bash
   docker compose exec postgres psql -U yupay_app -d yupay \
     -c "SELECT u.id, tl.tg_user_id, u.roles FROM users u JOIN telegram_links tl ON tl.user_id = u.id ORDER BY u.created_at DESC LIMIT 5;"
   ```

5. Grant the role:

   ```bash
   docker compose exec api python -m yupay.scripts.grant_admin --tg-id <TG_ID>
   ```

6. **No re-login is required** — the role check runs per-request against the DB.
   Refresh the page and you're in.

## Revoking admin

```bash
docker compose exec api python -m yupay.scripts.grant_admin --tg-id <TG_ID> --revoke
```

The next request the user makes will fail the role check (403). Existing
access tokens stay technically valid until expiry, but every admin endpoint
re-reads the role on each call, so they cannot do anything.

## Reviewing the admin set

```bash
docker compose exec postgres psql -U yupay_app -d yupay -c \
  "SELECT u.id, u.display_name, tl.tg_user_id, tl.tg_username, u.roles
   FROM users u LEFT JOIN telegram_links tl ON tl.user_id = u.id
   WHERE u.roles ? 'admin' ORDER BY u.created_at;"
```

The partial index `ix_users_roles_admin` makes this O(admins), not O(users).

## Troubleshooting

- **403 after grant**: confirm `roles` actually contains `"admin"` (case-sensitive,
  no whitespace) — `grant_admin` always sorts and dedupes.
- **Telegram widget never fires `onauth`**: check that `VITE_TELEGRAM_BOT_USERNAME`
  is set in the admin container's build args and that the bot's domain is set in
  BotFather (`/setdomain → admin.yupay.io`).
- **401 on every API call**: the SPA refreshed the page after a logout and lost
  the token — log in again.
