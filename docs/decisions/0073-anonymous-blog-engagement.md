# 0073. Anonymous blog likes and views via a reader cookie

- **Status**: Accepted
- **Date**: 2026-09-12
- **Deciders**: owner, engineering
- **Tags**: backend | frontend | security | data

## Context and problem statement

Editorial posts need public like and view counts. Guests must be able to like
without signing in. Counting by IP would put an inbound address in the
engagement path, which AGENTS.md forbids logging and which is a weak identity
anyway (CGNAT, shared offices).

## Decision drivers

- Likes work for a signed-out reader
- One like and one counted view per reader per post
- Do not persist or log an inbound IP or the raw cookie
- Public GETs stay cacheable; writes are explicit POSTs

## Considered options

1. **HttpOnly first-party cookie**, hashed at rest (`SHA-256`), unique rows
2. **IP hash** — inbound address on the write path; banned as PII here
3. **Require login** — kills the guest like the owner asked for

## Decision outcome

**Chosen option:** Option 1. `yp_blog_reader` is minted on the first
`POST /blog/{slug}/view` or like, scoped like the refresh cookie
(host-only in dev, `.yupay.uz` in prod). The table stores only the hash.
`like_count` / `view_count` live on `blog_posts` so list cards stay one
query. Repeat view or like is a no-op. Unlike is `DELETE`. Mutations take
`Idempotency-Key` and replay through `idempotent_responses`.

### Positive consequences

- Guests like; signed-in users use the same cookie (login is not required)
- GET `/blog` stays a read

### Negative consequences

- Clearing cookies lets the same person like/view again
- ISR cards can lag the live count by `revalidate = 300`

## Validation

Integration test: anonymous view increments once, like toggles, replayed
Idempotency-Key does not double-count.

## Alternatives considered (detail)

### Option 1 — cookie hash

Pros: guests can like; no inbound IP on the path; GET stays cacheable.
Cons: clearing cookies resets identity; ISR cards lag live counts.

### Option 2 — IP hash

Pros: no cookie.
Cons: inbound address on the write path; CGNAT collapses many people into one
hash; AGENTS.md treats that address as PII.

### Option 3 — require login

Pros: stable identity.
Cons: kills guest likes, which the owner asked for.

## References

- [ADR-0072](./0072-editorial-blog.md)
- Spec `docs/superpowers/specs/2026-09-12-blog-design.md` §9
