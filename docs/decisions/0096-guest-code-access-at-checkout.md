# 0096. Guest code access handed to the browser that placed the order

- **Status**: Accepted
- **Date**: 2026-10-04
- **Deciders**: @jamaomonov
- **Tags**: backend | frontend | security

## Context and problem statement

ADR-0042 made the delivered email the only way a guest reaches their codes on
the web: the order-scoped `guest_order` token rides the email's link, and
`POST /orders/{id}/code-access` re-mails it.

Order 01A102A2 (2026-10-03, Roblox 200 Robux, paid via Payme) showed the gap.
The guest typed an email address that does not exist. Resend reports all five
messages for the order (the delivery mail and four re-sends) as `bounced`. The
order page could only offer to «send the link again», to the same dead address,
so the buyer had paid and could not see the code. Nothing was logged on our side:
Resend accepts the send (2xx) and the bounce happens later.

## Decision drivers

- A typo in the email must not lock a buyer out of goods they paid for.
- ADR-0042's guarantee holds: knowing an email is never enough to read codes.
- No new screen in guest checkout.

## Considered options

1. **Return the `guest_order` token from `POST /orders`** for a guest order; the
   web keeps it per order in `localStorage` and the order page uses it when the
   URL has no `?access=`. The email link stays the way back from another device.
2. **Confirm the email before payment** (OTP). Closes typos too, but adds a step
   to the primary funnel.
3. **Let the guest correct the email** on the order page. Whoever holds the page
   could then redirect the codes — an attacker-controlled address by design.

## Decision outcome

**Chosen option:** 1. It is ADR-0042's rejected option 3 ("bind the checkout
token to the order") added _beside_ the magic link rather than instead of it,
which is what that option lacked: the new device still recovers through email.

The token is the one ADR-0042 already defines — same claims, same 7-day TTL,
same `X-Guest-Email` check — and it reaches only the caller of `POST /orders`.
A replay of the same `Idempotency-Key` returns the same order, so it grants
nothing placing the order did not. `GET /orders/{id}` never carries it.

### Positive consequences

- A bounced or mistyped email no longer strands a paid order on the device that
  bought it.
- No change to the email-only `guest` token: it still cannot read codes.

### Negative consequences

- A bearer for one order's codes sits in `localStorage` for up to 7 days. Anyone
  with that browser's storage could already open the guest order history and the
  payment flow; the codes become reachable there too.
- Another device still depends on the email; a mistyped address still needs
  support there.

## Validation

- `tests/integration/test_guest_delivery_access.py::test_order_create_hands_the_guest_its_own_code_access`:
  the create response carries a token, a replay does too, a read does not, and
  the token opens that order's deliveries.
- `apps/web/src/components/order/OrderStatus.test.tsx`: a guest with a stored
  token sees the code and no «request a link» block.
