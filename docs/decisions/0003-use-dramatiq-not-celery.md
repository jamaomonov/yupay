# 0003. Use Dramatiq + Redis for background work

- **Status**: Accepted
- **Date**: 2026-05-15
- **Deciders**: founding team
- **Tags**: backend, infra

## Context

YuPay needs a task queue for: payment webhook handling, supplier fulfillment, outbox relay,
notifications, FX refresh, reconciliation. Constraints: asyncio FastAPI, idempotent
sagas, single-VPS day-one deploy, ~200 RPS peak.

## Decision

We adopt **Dramatiq** with a **Redis** broker.

## Drivers

- **Async-friendly**: Dramatiq 1.15+ supports async actors that integrate cleanly with
  FastAPI's event loop. Celery's async story remains awkward.
- **Operational simplicity**: Redis is already in the stack; no extra broker to run on the
  starting VPS.
- **Middleware**: built-in retries, dead-lettering, rate limits cover our reliability needs.
- **DX**: simpler than Celery; richer than RQ.

## Negative consequences

- Smaller ecosystem than Celery — some integrations (Flower equivalents, beat plugins) are
  thinner.
- If sagas grow >5 steps with branching, we may want **Temporal**; see "Migration path"
  below.

## Migration path to Temporal

Saga state is kept in DB (`fulfillment_tasks`), not in Dramatiq messages. When we adopt
Temporal, the existing **activities** (reserve, charge, fulfill, deliver, reward) become
Temporal activities; only the orchestrator is rewritten. No data migration required.

## Alternatives considered

- **Celery** — heavyweight, sync-first, "kitchen-sink" foot-gun.
- **RQ** — too thin; we'd reimplement features.
- **ARQ** — asyncio-native, smaller ecosystem and fewer middlewares.
- **Temporal** — best long-term, but ops overhead is too high day one.

## References

- [Dramatiq docs](https://dramatiq.io/)
- [ADR-0002](./0002-use-modular-monolith.md)
