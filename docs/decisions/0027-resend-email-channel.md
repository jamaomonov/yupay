# 0027. Transactional email channel via Resend

- **Status**: Accepted
- **Date**: 2026-06-05
- **Deciders**: @jamaomonov
- **Tags**: backend | infra

> **Amendment (2026-07-31): branded HTML templates.** The v1 plain f-string bodies
> were replaced with a shared, email-client-safe HTML shell (table layout, inline
> styles, brand palette, a bulletproof lime CTA button with an MSO fallback, and a
> dark header carrying the brand logo). Template **function signatures and the
> `EmailContent` value object are unchanged**, so callers and tests are unaffected;
> only the rendered markup changed. Email clients (notably Gmail) do not render SVG,
> so the header uses a **PNG logo** at `apps/web/public/logo/email-logo.png`. A new
> setting `email_logo_url` (env `EMAIL_LOGO_URL`, default `""`) points at a publicly
> reachable logo URL; when empty it falls back to
> `{web_base_url}/logo/email-logo.png`, and if that is also unset the header degrades
> to a text wordmark. Copy remains Russian-only.
>
> The delivered-order email now distinguishes **secret codes** (voucher / license
> keys — rendered as monospace chips with a "save them safely" copy) from
> **top-up receipts** (which deliver no code — rendered as a "✓ Зачислено · …"
> info row echoing the target account, with a "средства зачислены" copy). The
> dispatch splits deliveries into `(codes, credited)` via
> `_delivery_lines_for_email`, and `order_delivered_email` gained a `credited`
> parameter alongside the existing `codes`.

## Context and problem statement

Guests have been checking out by email since the storefront launched, but **no
transactional email has ever been sent** to them — no order confirmation, no delivery
notification, no error. The platform is effectively silent for non-Telegram users.

The new email/password auth path (ADR-0026) makes this gap critical: verification
emails and password-reset links _must_ reach users, or the auth feature is unusable.
At the same time, wiring a basic order-confirmation/delivery email for all guests is
the natural adjacent improvement: the infrastructure for it is the same Resend call and
we have the recipient email from checkout.

We need a **minimal transactional email channel** that can send four message types
(verify-email, password-reset, order-confirmation, order-delivered) without introducing
a full-blown email queuing system.

## Decision drivers

- Auth emails (verify / reset) must be delivered on the request path or very shortly
  after — a queueing delay of several minutes would break the UX of the verification
  and reset flows.
- Order emails (confirmation / delivery) are best-effort; a delivery failure must not
  degrade the order flow.
- A per-call `httpx` client avoids a long-lived connection pool and simplifies testing
  via `respx`.
- The project already uses `httpx` (FastAPI, `respx` contract tests); no new HTTP
  client library.
- Resend is listed as a supported SaaS option in AGENTS.md §2 and is already referenced
  in the config via `RESEND_API_KEY`.
- Templates must be independently reviewable and unit-testable without a real Resend
  account; plain f-string builders satisfy this.
- v1 can ship with Russian-only copy; per-locale copy is a follow-on.

## Considered options

1. **Postmark** — another SaaS transactional email provider.
2. **SMTP via a self-hosted MTA (Postfix / Exim)** — direct SMTP, no SaaS dependency.
3. **Worker-queued email** — enqueue via Dramatiq; a background worker calls Resend.
4. **Resend REST, per-call `httpx` client, on-request-path for auth / inline in
   notifications dispatch for orders** (chosen).

## Decision outcome

**Chosen option: Option 4.**

**Channel implementation.** `notifications/channels/email.py` exposes a single async
function `send_email(*, to, subject, html, text) -> str` that POSTs to
`https://api.resend.com/emails` with a per-call `httpx.AsyncClient` (timeout 10 s).
On non-2xx it raises `EmailSendError`; on network/timeout it also raises
`EmailSendError` wrapping the underlying `httpx.HTTPError`. The recipient address is
never logged (PII rule).

**Config.** Three new settings in `core/config.py`:

- `resend_api_key` (env `RESEND_API_KEY`, default `""`).
- `email_from` (env `EMAIL_FROM`, default `noreply@yupay.uz`).
- `email_from_name` (env `EMAIL_FROM_NAME`, default `YuPay`).
- `web_base_url` (env `WEB_BASE_URL`, default `""`): absolute URL of the web
  storefront, used to construct verification/reset/order links in emails.

When `resend_api_key` is empty `send_email` raises `EmailSendError` immediately; the
callers suppress this (best-effort), so dev environments without a key do not crash.

**Templates.** `notifications/templates.py` contains four dependency-free f-string
builders returning a frozen `EmailContent(subject, html, text)` Pydantic value object:

| Template function          | Triggered by                                         |
| -------------------------- | ---------------------------------------------------- |
| `verify_email_email`       | `POST /auth/register` (link to `/auth/verify`)       |
| `password_reset_email`     | `POST /auth/password/forgot` (link to `/auth/reset`) |
| `order_confirmation_email` | Order created (`notifications` dispatch)             |
| `order_delivered_email`    | Order delivered (`notifications` dispatch)           |

Templates are **Russian-only in v1**. Per-locale copy is deferred to a future i18n pass
(the function signature accepts a `link` and `order_id`; adding a `locale` parameter is
backward-compatible).

**Auth emails** (verify / reset) are sent on the **request path** inside
`auth/service.py` (`register_user`, `request_password_reset`). A caught
`EmailSendError` is suppressed: the user is already logged in (register) or the 204 has
already been determined (forgot). The user can re-request a verification link or reset
link without losing their account.

**Order emails** are wired into the existing `notifications/service.py` dispatch next
to the Telegram notification branch, gated on `order.guest_email` (or the registered
user's email).

> **Correction (2026-08-25).** The parenthetical described an intent the code never
> had: the branch read `order.guest_email` alone, which is NULL on every signed-in
> order by construction (`ck_orders_actor_exclusive`), so registered buyers were
> mailed nothing — 107 delivered orders on prod, 36 of them belonging to accounts
> with an address on file. Resolution now runs `order.guest_email` →
> `order.delivery_email` (what was typed at checkout) → `users.delivery_email` (the
> mini app's settings screen) → `users.email`. `users.delivery_email` is separate
> from the login identity on purpose; see the column comment for why a settings
> screen must not write `users.email`. The email branch is placed **before** the Telegram `chat is None`
> early-return so that guests who have no Telegram account always receive an email. Both
> branches are best-effort: exceptions are caught and logged, never propagated.

**Testing.** `respx`-mocked contract tests cover: `send_email` success (asserts
`Authorization: Bearer <key>` header and returns the Resend `id`); 4xx raises
`EmailSendError`; 429 raises `EmailSendError`. Template unit tests assert each builder
embeds the provided link and order ID in both `html` and `text`.

### Positive consequences

- Guests receive confirmation and delivery emails — the long-standing post-checkout
  silence is closed.
- Email/password auth is fully operational (verify + reset links actually arrive).
- The channel is independently testable with `respx` and does not require a real Resend
  account in CI.
- No new HTTP client library; no new message broker.
- Templates are pure Python; any contributor can read and edit copy without framework
  knowledge.

### Negative consequences

- Auth emails are on the request path: a slow Resend API (> 10 s) delays the register /
  forgot response. Mitigated by the 10 s timeout and error suppression, but not
  eliminated.
- If Resend is down or the key is misconfigured, verification and reset emails are
  silently dropped. The user's account remains usable (login still works; they can
  re-request verification). A monitoring alert on `EmailSendError` rate is recommended.
- Russian-only templates in v1; until the i18n pass, non-Russian users receive
  Russian-language emails.
- A new SaaS dependency: Resend outages directly affect the email channel. DKIM / SPF
  must be configured on the sending domain before going to production.

## Validation

- Contract tests: `send_email` success / 4xx / 429 scenarios all pass in CI (`respx`
  mock).
- Unit tests: all four template builders return `EmailContent` with non-empty `subject`,
  `html`, and `text`; the provided link/order ID appears in both bodies.
- Manual: register a new account → verification email arrives at the real address;
  `POST /auth/password/forgot` → reset email arrives; checkout → order confirmation
  email arrives; order reaches `delivered` → delivery email arrives.

## Alternatives considered (detail)

### Option 1 — Postmark

Pros: comparable SaaS quality, strong deliverability reputation, template editor.
Cons: AGENTS.md §2 already lists Resend as the email SaaS choice alongside Postmark;
switching is a one-line config change if needed. No compelling reason to prefer Postmark
over Resend for a v1.

### Option 2 — SMTP / self-hosted MTA

Pros: no SaaS dependency; full control over deliverability tuning.
Cons: operating a mailserver (SPF, DKIM, DMARC, bounce handling, IP reputation) is
significant ongoing ops work, disproportionate to the v1 scope. A single VPS IP has
poor cold-start reputation for transactional mail.

### Option 3 — Worker-queued email via Dramatiq

Pros: decouples the request path from email latency; retries on transient Resend
failures; a full audit log in the task queue.
Cons: adds Dramatiq task wiring for what are presently three small send calls; the
benefit is marginal when the p99 Resend latency is well under 1 s and failures are
suppressed anyway. Queuing is the natural upgrade path if email volume grows or SLA
tightens.

## References

- [ADR-0026](./0026-web-password-auth.md) — web password auth (consumer of verify/reset emails)
- `docs/architecture/cache-keys.md` — no cache keys owned by the email channel
- `docs/architecture/sequence-diagrams/web-auth.mmd` — shows where emails are sent in each flow
- `docs/superpowers/specs/2026-06-05-web-accounts-design.md` — feature design spec §4.1
- `apps/api/src/yupay/modules/notifications/channels/email.py` — channel implementation
- `apps/api/src/yupay/modules/notifications/templates.py` — template builders
- `apps/api/src/yupay/modules/notifications/service.py` — dispatch wiring
