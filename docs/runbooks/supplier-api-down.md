# Runbook — Supplier API down

## Symptoms

- Alert `SupplierDown` firing.
- Customers see orders stuck in `awaiting_fulfillment` for > 10 min.

## Triage

1. Check supplier status (vendor portal, status page).
2. Grafana → "Suppliers" dashboard.
3. Check circuit breaker state: `make logs service=worker | grep purgatory`.

## Mitigation

1. **Route around the supplier**:
   - For SKUs that have an in-house code warehouse fallback, the `sourcing` module switches
     automatically on circuit-breaker open.
   - For SKUs that depend solely on this supplier, **disable affected SKUs** in the
     storefront:
     ```bash
     docker compose exec api yupay catalog disable-sku --supplier <slug>
     ```
2. Pending orders that cannot be fulfilled within 30 min are auto-refunded to wallet by the
   `fulfillment.timeout_handler` (configured per SKU).
3. Notify customers via the existing order-status WebSocket and a templated email/Telegram
   message.

## Recovery

1. Re-enable SKUs once the supplier is healthy and circuit breaker closes:
   ```bash
   docker compose exec api yupay catalog enable-sku --supplier <slug>
   ```
2. Replay supplier orders stuck without `external_id`:
   ```bash
   docker compose exec api yupay suppliers replay --supplier <slug>
   ```

## Post-incident

- Review supplier SLA in `apps/api/src/yupay/modules/integrations/adapters/<supplier>.py`
  and adjust timeouts/breaker thresholds if needed (add an ADR if the change is structural).
