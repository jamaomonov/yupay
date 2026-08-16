# 0044. Store an unhashed IP per order as chargeback evidence

- **Status**: Accepted
- **Date**: 2026-08-07
- **Deciders**: @jamaomonov
- **Tags**: security | data | payments

## Context and problem statement

We sell digital goods that are delivered automatically within minutes, to a public game ID
that is usually not the payer's own account, often to a guest with no account of their own.
That is the textbook shape a carder looks for: irreversible, fast, and impossible to claw
back from the recipient.

When a cardholder disputes such a payment, the loss lands on us. The acquirer contracts are
explicit about it:

- **Payme**, Общие условия п. 9.6 — «Поставщик … самостоятельно и собственными силами
  осуществляет возврат суммы платежа со своего расчетного счета, при этом Платежная
  организация никаких обязательств по возврату платежа не несет.»
- **Payme**, п. 6.2.3 — if we do not produce documents within **5 calendar days**, the claim
  closes in the issuing bank's favour and the amount is withheld from our payouts.
- **Payme**, п. 6.3.2 — transaction documents must be retained **540 days** and produced
  within **1 working day** on request. п. 6.3.4 adds that our own technical failures are
  explicitly not an excuse.
- **CLICK**, Типовые условия — the word "chargeback" does not appear at all; пп. 5.2/5.3 put
  the relationship with the payer on us. The absence of a defined procedure is not protection.
- **Uzum Bank** — silent on disputes, and п. 3.3.2 lets the bank drop us unilaterally and
  without explanation over operations it considers risky.

Against those deadlines we had almost nothing. `orders.ip_hash` / `ua_hash` columns existed
but no caller ever populated them, so they were always NULL — and a SHA-256 would not have
helped anyway: an issuing bank cannot be shown a hash and asked to take our word that it
matches. Hashes support correlation (spotting many orders from one address), not evidence.

The blocker is that AGENTS.md §9 says plainly: **never store PII, including IP**. Capturing
what a dispute actually requires means taking a deliberate exception to our own rule.

## Decision drivers

- A dispute answered with "we have no record of who placed this" is a dispute lost, and the
  loss is the full transaction plus the wholesale cost we already paid the supplier.
- Losing an acquirer hurts more than losing a transaction. Payme п. 16.3.1 allows suspension
  and termination over suspicious operations; Uzum п. 3.3.2 needs no reason at all.
- §9 exists to keep us from leaking customer data through logs and responses. Evidence stored
  deliberately, in one table, behind admin auth, with an enforced expiry is a different risk
  from an IP smeared across log lines — but only if it is actually all three of those.
- Collecting more than a dispute needs is not free: every extra field is more to leak.

## Considered options

1. **Hashes only** — keep the existing (empty) `ip_hash`/`ua_hash` scheme and populate it.
2. **Raw IP and User-Agent** in a dedicated table with retention and admin-only access.
3. **Raw IP with masking after 90 days** — full address during the window most disputes
   arrive in, truncated to a subnet afterwards.

## Decision outcome

**Chosen option: 2.** Option 1 is not evidence; adopting it would have been a decision to
lose disputes while feeling careful. Option 3 was rejected because it hedges the wrong risk:
the masking window would have to be guessed, and a dispute landing on day 400 — which the
540-day retention requirement exists precisely to cover — would find a record already
degraded past use. Collecting the data at all is the decision; keeping it usable for exactly
as long as we are obliged to hold it is not an additional one.

Scope is deliberately narrow:

- **One table, `order_evidence`**, one row per order, written once and never updated. Editable
  evidence is not evidence.
- **Only what a dispute uses**: IP, User-Agent, Accept-Language, and passive browser hints
  (timezone, locale, screen). No canvas/font/audio fingerprinting — that identifies a device
  across sites, is a separate consent question, and would not make a pack stronger.
  `navigator.platform` is not collected either: the User-Agent already carries it.
- **`purge_after` is stamped per row at capture time**, not computed from config at delete
  time. Shortening the policy later must not retroactively extend the life of data collected
  under an earlier promise. Default is 600 days: Payme's 540 plus room for a dispute arriving
  on day 539 and the exchange that follows.
- **One reader**, `GET /admin/orders/{id}/evidence`, behind `require_admin`. There is no
  public counterpart and there must not be one.
- **Every read is audited** as `admin.evidence_viewed` on the order timeline, carrying the
  acting admin — the same rule the delivery-artifact read follows. Data kept in its own table
  with an enforced expiry, precisely because it is sensitive, cannot also be readable without
  a trace. The event is appended after the pack is assembled, so our access log never travels
  to the acquirer as part of their answer. The admin surface (the "Контекст покупателя" card
  on the order page) keeps it collapsed until an operator asks, so opening an order does not
  itself log a view or put an address on screen mid-screen-share.
- **Never fails a sale.** The capture runs after the order is created, inside a SAVEPOINT. A
  bare `try/except` would not be enough: the request's transaction commits after the route
  returns, so a failed statement poisons it and the _order_ is lost at commit — the exact
  outcome the guard claims to prevent.

## Positive consequences

- A pack can be produced in one request, which is what the 5-day and 1-working-day clocks
  actually demand.
- The same capture is the foundation for velocity rules (many orders, one address) when
  anti-fraud work starts.
- Consolidating three copies of the client-IP parsing into `core/client_ip` means the rate
  limiter, the auth guard and the evidence record can no longer disagree about who the caller
  was.

## Negative consequences

- We now hold personal data we previously did not, with the disclosure and lawful-basis
  obligations that follow. The privacy notice is updated in the same change.
- The evidence is only as trustworthy as the edge config: `infra/edge/Caddyfile` _overwrites_
  `X-Forwarded-For` rather than appending, which is what makes the leftmost entry unspoofable.
  Changing that to append would silently turn this table into attacker-controlled data.
- Evidence written from today forward. Orders already placed cannot be reconstructed, and we
  remain answerable for them for another 540 days.

## Validation

- An integration test forces a database-level failure inside the capture and asserts the order
  still commits — the savepoint claim, proven rather than asserted.
- A second test fetches the pack as an admin end-to-end; it is what caught that asyncpg returns
  `ipaddress` objects for INET columns, which would have 500'd a route that type-checked clean.
- The real validation is the first dispute: if a pack cannot answer it, this decision was
  scoped wrong.

## Open questions

- **Data localisation.** Uzbek personal-data law has localisation requirements and the database
  runs on a VPS in France. Whether that applies to this data and this business needs a lawyer's
  answer, not an engineer's guess.
- **3-D Secure.** If authentication shifts liability to the issuer, it prevents disputes rather
  than arguing them, and would change how much this table has to carry. Open with the acquirers.

## References

- [ADR-0011](./0011-order-fsm-and-snapshots.md) — the order FSM and `order_events`, the
  timeline half of a pack
- [ADR-0030](./0030-shared-edge-proxy-on-a-co-hosted-vps.md) — the edge whose header rewrite
  makes the captured address trustworthy
- Payme, Общие условия — <https://cdn.payme.uz/terms/ru/general_conditions.html>
- CLICK, Типовые условия — <https://click.uz/click/click_terms_ru.pdf>
