# 0074. Blog IndexNow via the worker queue

- **Status**: Accepted
- **Date**: 2026-09-12
- **Deciders**: owner, engineering
- **Tags**: backend | infra

## Context and problem statement

A published blog URL goes live without a web deploy. `make indexnow` already
pings Bing/Yandex from the live sitemap, but someone has to remember to run
it. Google does not speak IndexNow; Yandex does, and that is the CIS crawl
we care about. Calling IndexNow from `POST /admin/blog/.../publish` would
put a third-party HTTP call on the request path, which AGENTS.md forbids.

## Decision drivers

- Publish and archive stay fast and do not fail because IndexNow is down
- The ping is the same transaction as the status change, so it cannot be
  forgotten
- Localhost and CI never POST to `api.indexnow.org`

## Considered options

1. **Inline HTTP in the publish handler** — violates the request-path rule
2. **Scheduler sweep** — eventual, easy to miss a just-published row
3. **Postgres outbox + worker drain** (ADR-0064 shape)

## Decision outcome

**Chosen option:** Option 3. `publish_post` / `archive_post` insert
`blog_indexnow_pings` and `pg_notify('blog_indexnow_queue')` in the caller's
transaction. `apps/worker` drains the table. URLs are always `https://yupay.uz`
(locale prefix like the storefront). The POST runs only when
`ENVIRONMENT=prod`; everywhere else the row is `skipped`. One attempt; a miss
is `failed` and `make indexnow` remains the operator fallback. Google is
unchanged (sitemap + GSC).

### Positive consequences

- Scheduled publish (`blog_publish_due`) reuses `publish_post`, so it pings too
- A down IndexNow cannot roll back an editorial publish

### Negative consequences

- A third worker queue (concurrency 1)
- Edits to an already-published body do not ping; archive + republish or
  `make indexnow` if a recrawl is needed

## Validation

Integration tests: publish writes a `pending` row; drain outside prod marks
`skipped`; drain with `live=True` POSTs and marks `done`.

## References

- [ADR-0064](./0064-postgres-fulfilment-queue.md)
- [IndexNow protocol](https://www.indexnow.org/documentation)
- `docs/runbooks/seo-indexing.md`
