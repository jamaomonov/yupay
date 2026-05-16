# Runbook — Payment provider outage

## Symptoms

- Alert `PaymentProviderDown` firing (5xx rate > 30% over 5 min, or 0 successful intents in
  10 min for a provider that normally has traffic).
- Customer reports: "I can't pay with Click / Payme / Stripe".

## Triage (5 min budget)

1. Check provider status page (Stripe, YooKassa, Click, Payme).
2. Grafana → "Payments" dashboard → provider panel: success rate, webhook lag, error mix.
3. Check our own logs for the provider: `make logs service=api | grep <provider>`.

## Mitigation

If the provider is genuinely down:

1. **Disable the provider in the UI** without code changes:
   ```bash
   # Toggles a feature flag in Redis; storefront re-checks on each render
   docker compose exec api yupay providers disable --provider <slug> --reason "<provider> outage"
   ```
2. Post a banner on the affected surfaces (web + miniapp) via the admin tool or
   `feature_flags` CLI.
3. Notify ops channel.

If only **webhooks** are degraded (intents create OK, callbacks late):

1. Our reconciler job (`payments.reconcile_in_flight`) polls intents every 60 s. As long as
   it's running, no manual action is needed unless the lag exceeds 30 min.
2. Verify with: `docker compose logs scheduler | grep reconcile_in_flight`.

## Recovery

1. Re-enable provider:
   ```bash
   docker compose exec api yupay providers enable --provider <slug>
   ```
2. Replay any payments stuck in `pending` for > 15 min:
   ```bash
   docker compose exec api yupay payments replay --provider <slug> --older-than 15m
   ```
3. Remove banners.

## Post-incident

- File a post-mortem using `docs/runbooks/incident-template.md`.
- If the outage exceeded 30 min or impacted > 100 customers, write a public status update.
