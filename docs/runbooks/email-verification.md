# Runbook — Email verification & post-payment return

> Introduced with the Phase 3 web-orders work. Covers the operational
> consequences of enforcing email verification at login and of the payment
> `return_url` change.

## What changed

- **Password login now requires a verified email.** `POST /auth/login` returns
  `403` with `type` `.../email-unverified` when `users.email_verified_at IS
NULL`. Telegram, guest-checkout, and admin-dev logins are **not** affected.
- **Registration no longer logs the user in.** `POST /auth/register` returns
  `{status: "verification_required", email}` and sends a verify link. The user
  logs in only after clicking it (`POST /auth/verify-email` sets
  `email_verified_at` and returns a session).
- **Existing users were grandfathered** to verified by Alembic migration
  `0036_grandfather_email_verified` (forward-only). No pre-existing account is
  locked out.

## Operational consequence: the mailer is now load-bearing

Because a new user cannot log in until they verify, **outbound email
(Resend/Postmark) must work in production** or signups get stuck. The email send
is scheduled off the request path, so a mailer outage fails silently at send
time — it does not error the request.

**If users report "can't log in after signing up":**

1. Check the mailer: `make logs service=api | grep -i "email\|resend\|verify"`
   for send failures; verify the email provider API key is present and valid.
2. Have the user use **Resend** on the verify screen (`POST
/auth/resend-verification`, always 204, rate-limited) — it re-sends the link.
3. As a last resort (mailer down, user blocked), an operator can mark the
   account verified directly:
   ```sql
   UPDATE users SET email_verified_at = now()
   WHERE email = :email AND email_verified_at IS NULL;
   ```
   Prefer fixing the mailer; use this only to unblock a specific stuck user.

Note: verify links are **single-use** (Redis `auth:emailverify:{jti}`). An email
security scanner that pre-fetches links, or a double-click, can consume the
token — the user then sees the "link invalid/expired" state and must use Resend.
This is expected, not a bug.

## Payment return_url / WEB_BASE_URL deploy invariant

The acquirer `return_url` now defaults to the storefront and a client-supplied
value is validated **same-origin** as `WEB_BASE_URL`. The web sends
`${origin}/{locale}/orders/{id}` so the customer lands on their live order.

- **`WEB_BASE_URL` must equal the canonical web origin** (`https://yupay.uz`).
  If it is unset or a different origin (e.g. `www.` / `app.`), every web card
  intent will `422` (`return_url must be on the storefront origin`). Verify
  after any deploy that changes env: `curl` a checkout intent, or check
  `infra/secrets-example/api.env` matches prod.
- No-`return_url` callers (currently the Mini App, which reopens itself and
  polls) fall back to `${WEB_BASE_URL}/checkout/return`. **Follow-up:** the web
  `/checkout/return` page does not exist yet — a no-return_url card flow would
  land on a 404. This predates Phase 3 (the old default was also a placeholder)
  and does not affect the web card flow (which returns to `/orders/{id}`); track
  adding a minimal `/checkout/return` page separately.
