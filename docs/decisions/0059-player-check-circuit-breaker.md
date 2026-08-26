# 0059. Break the circuit on the player check, not on fulfilment

- **Status**: Accepted
- **Date**: 2026-08-26
- **Deciders**: @jamaomonov
- **Tags**: backend | integrations | observability

## Context and problem statement

`G2bClient._request` retries 429 and 5xx four times with a 1→2→4→8s backoff. That is the
right policy for order fulfilment: the money is already taken, the work runs in a background
worker, and giving up early only pushes the order into the manual queue for a human.

It is the wrong policy for the storefront player check. That check is advisory — ADR-0031
established it never blocks checkout, and every failure mode is folded into
`status: "error"`, which the storefront renders as "couldn't check" and never as a bad id.
So while G2B is unwell, each customer waits through roughly fifteen seconds of sleeping to
arrive at a verdict that was already knowable from the previous customer's failure.

Measured on prod (2026-08-26), a healthy cold check costs 830ms for Mobile Legends and up to
4.9s for Free Fire; virtually all of that is waiting on G2B, since a cache hit is ~150ms of
which ~120ms is network round trip. During an outage the retry budget stacks on top of that.

`docs/security/threat-model.md` already lists "per-supplier outbound token bucket; circuit
breaker" as the intended control for supplier-side DoS. Neither existed in code.

## Decision drivers

- A customer waiting on an optional lookup should be told quickly, not thoroughly.
- Nothing about this may make an order more likely to fail. Fulfilment is money.
- A guard that can itself fail must fail open — an unreachable Redis must not become the
  outage the breaker was added to contain.
- The deployment is meant to stay horizontally splittable without a rewrite, so breaker
  state cannot live in one process's memory.

## Considered options

1. **Breaker inside `G2bClient._request`** — every G2B call, fulfilment included, fast-fails
   once the circuit opens.
2. **Breaker around the advisory player check only** — fulfilment keeps its full retry budget.
3. **Shorten the retry budget for the check instead** — pass a smaller `max_retries` when the
   caller is the player check.

## Decision outcome

**Chosen option: option 2.**

Option 1 changes a money path to fail faster during exactly the conditions where patience is
most valuable. An open circuit would convert supplier flakiness into orders landing in the
manual queue, trading a background retry that costs nobody anything for human work.

Option 3 helps but does not solve it: with the budget cut to one attempt each, a hundred
customers still each pay a full timeout to learn the same fact.

The breaker lives in `modules/integrations/breaker.py` as `SupplierBreaker`, keyed by circuit
name so one supplier's outage cannot silence another's checks. It opens after 3 consecutive
failures and stays open for 30s. There is no separate half-open state: the Redis key simply
expires, and the next call runs for real — closing the circuit if the supplier recovered,
re-opening it if not. A success always clears the run, so a probe can end an outage rather
than merely decline to extend it.

State is in Redis rather than in-process so a second API worker inherits what the first
learned instead of rediscovering it on its own run of customers.

`threshold = 0` disables the breaker entirely — a kill switch that does not need a redeploy.

### Which failures count

Not every error is evidence about G2B's health, and the circuit is shared across the supplier
rather than held per game — so counting the wrong things lets one broken brand silence the
check for all seventeen.

- **Counted:** `UpstreamUnavailableError` — network trouble and exhausted retries. These are
  exactly the failures that cost the customer the 1→2→4→8s budget, which is what the breaker
  exists to stop paying repeatedly.
- **Not counted:** a non-retryable 4xx such as "unknown game". That is one product's broken
  mapping, it is raised immediately with no backoff to save, and it says nothing about
  whether G2B is up.
- **Counted, unusually:** HTTP 401. It also fails fast, so no customer is waiting on it — but
  `G2bClient` warns that a few 401s in a row get our IP banned at G2B, and that ban would take
  order fulfilment down with it. Backing off a rejected key protects the money path from the
  advisory one.

### Positive consequences

- During a G2B outage a check costs ~150ms instead of ~15s, with the same visible answer.
- Fulfilment behaviour is byte-for-byte unchanged.
- `breaker_open` / `breaker_closed` log events make supplier outages legible in Loki, which
  previously showed only a rise in `player_check_failed`.

### Negative consequences

- For up to 30s after a blip, checks that would have succeeded return `error`. Acceptable:
  the check is advisory and the customer can retry, or simply proceed.
- One more piece of Redis state to reason about during an incident. Documented in
  `docs/runbooks/g2b-troubleshooting.md`.
- The threat model's "outbound token bucket" half is still not implemented. G2B's ceiling is
  1000 requests / 10s per key and observed organic load is ~4 checks per hour, so this is not
  urgent — but it remains open.

## Validation

- `apps/api/tests/unit/test_supplier_breaker.py` covers opening, closing, isolation between
  circuits, the kill switch, and fail-open on a broken Redis.
- `apps/api/tests/integration/test_player_check_endpoint.py` asserts end to end that an open
  circuit stops calls reaching G2B, and that a recovered supplier closes it. Both were
  confirmed to fail with the breaker disabled.
- In production: `breaker_open` should appear during a G2B incident and be followed by
  `breaker_closed` within a minute of recovery. If a circuit opens while G2B is healthy, the
  threshold is too tight.
