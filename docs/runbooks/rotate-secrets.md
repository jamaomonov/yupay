# Runbook — Rotate secrets

> Performed quarterly. Triggered ad-hoc on suspected leak.

## Scope

The following secrets are rotated together:

- JWT signing keys (`JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY`, Ed25519)
- Postgres app user password
- Redis password
- Payment provider API keys (Stripe, PayPal, YooKassa, Click, Payme, Uzum, crypto)
- Supplier API keys (one entry per supplier in `infra/secrets/suppliers.enc.env`)
- Telegram bot token (only on suspected leak — rotating it forces all webhooks to re-bind)
- Email provider API key
- `sops` age keys (only on operator turnover)

## Procedure

1. **Generate new values**: see `scripts/gen-secret.sh` for each kind.
2. **Update `infra/secrets/*.enc.env`** via `sops`:
   ```bash
   sops infra/secrets/api.enc.env
   ```
3. **Deploy** — workflow `deploy.yml` re-syncs decrypted envs and restarts services.
4. **Revoke old values** in the provider dashboard (Stripe, etc.) **after** the deploy is
   verified.
5. **Document** the rotation in `docs/runbooks/secret-rotation-log.md` with date + operator.

## Verification

- Curl `/readyz` returns 200.
- A test payment intent on a single provider completes successfully.
- A test supplier `get_balance` call succeeds.

## On suspected leak

- Treat as SEV1. Rotate **immediately**, do not wait for the quarterly window.
- After rotation, file a post-mortem identifying how the leak occurred and the action items
  to prevent recurrence (typically: tighten access, add a secret-scanning rule).
