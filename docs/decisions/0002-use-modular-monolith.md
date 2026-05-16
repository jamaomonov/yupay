# 0002. Use a modular monolith on FastAPI

- **Status**: Accepted
- **Date**: 2026-05-15
- **Deciders**: founding team
- **Tags**: backend, architecture

## Context

YuPay must ship quickly with a small team, but its domain (payments, fulfillment, wallet,
suppliers, notifications) is naturally pluri-modular. Adopting microservices day one would
slow delivery; a tangled monolith would block extraction later.

## Decision

We adopt a **modular monolith on FastAPI**. Each domain module lives under
`apps/api/src/yupay/modules/<name>/` with a narrow public interface in `api.py`. No
cross-module SQL joins; modules communicate either through `api.py` or through outbox-backed
domain events.

## Consequences

- Day-one velocity: one repo, one app, one deploy unit.
- Extraction path is well-defined: when load demands, copy a module's folder + migrations,
  replace the in-process import in callers with an HTTP/gRPC client that mirrors `api.py`.
- Strict discipline required: cross-module SQL joins are prohibited in CI (review-only at
  first, lint rule planned).

## Alternatives considered

- **Microservices from day one** — rejected: ops overhead and inter-service coordination
  burn weeks before the first user.
- **Unstructured monolith** — rejected: cheap up front, expensive to untangle later.

## References

- [ADR-0003](./0003-use-dramatiq-not-celery.md)
- [`docs/architecture/module-map.md`](../architecture/module-map.md)
