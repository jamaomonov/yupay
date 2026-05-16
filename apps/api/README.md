# apps/api — YuPay FastAPI backend

Modular monolith. See `docs/architecture/module-map.md` for the full module list and
`AGENTS.md` § "Where to put new code" for placement rules.

## Layout

```
src/yupay/
├── main.py          # FastAPI entrypoint
├── bootstrap.py     # composition root: DI wiring, router mounting
├── core/            # shared kernel (config, db, redis, logging, outbox, idempotency, ...)
├── modules/         # domain modules — each owns its tables and exposes api.py
└── api/
    ├── v1/          # versioned HTTP routers
    └── webhooks/    # per-provider webhook routes
```

## Running locally

```bash
make dev-api        # foreground, requires postgres + redis already up
# or
make dev            # full docker-compose stack
```

## Migrations

```bash
make migrate                       # apply all
make migration name=add_orders     # autogenerate
```

## Tests

```bash
make test-py
```

Integration tests require Docker (testcontainers Postgres + Redis).
