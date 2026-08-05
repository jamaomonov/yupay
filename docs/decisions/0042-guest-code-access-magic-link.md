# 0042. Order-scoped magic-link token for guest code access

- **Status**: Accepted
- **Date**: 2026-08-05
- **Deciders**: @jamaomonov
- **Tags**: backend | frontend | security

## Context and problem statement

Guest buyers (no account) receive an email at checkout and can view their order on
the web. To authorise API calls they present a `Guest <jwt>` token minted by
`POST /auth/guest` from **an email address alone** — the token is freely mintable
by anyone who supplies the email. That token also unlocked
`GET /orders/{id}/deliveries`, which returns the order's **delivered voucher /
gift codes** (bearer instruments — whoever holds the code can redeem it).

Consequence (security audit finding #1, an IDOR): anyone who knows a buyer's email
could mint a guest token, supply that email, pass the owner check, and read the
buyer's delivered codes. Knowing an email — not a secret — was enough to steal
goods.

The delivered email already ships the codes inline to the order's address, so the
buyer's inbox is the real proof-of-ownership channel. The web order page just needs
a way to re-display those codes securely for a returning guest.

## Decision drivers

- Knowing an email must not grant access to another order's delivered codes.
- Keep guest checkout low-friction (it is the primary, SEO-driven funnel).
- Reuse the existing delivered email rather than add a separate verification step.
- Stay consistent with the existing `X-Guest-Email` header pattern.

## Considered options

1. **Order-scoped magic-link token** — a new `guest_order` JWT, minted only
   server-side, carrying the specific `order_id` it unlocks plus the email hash.
   It rides the `?access=` param of the link in the delivered email. The
   deliveries endpoint requires it (the email-only `guest` token no longer works
   for codes).
2. **OTP / email code** — email a one-time code the guest types in to unlock
   codes. Strongest, but adds a screen and server-side OTP state.
3. **Bind the checkout guest token to `order_id`** — no email involved, but a
   returning guest (new device, expired token) could never recover access.

## Decision outcome

**Chosen option:** Option 1. It closes the IDOR (knowing the email is no longer
enough — you need the order-scoped token that was mailed to the buyer), reuses the
delivered email as the delivery channel, and adds zero steps for the common case
(the buyer clicks the link in their email). A `POST /orders/{id}/code-access`
endpoint re-mails a fresh link for the expired/lost case; it is non-enumerating and
only ever mails the order's own address, never the caller's input.

The `guest_order` token unlocks **only** its one `order_id`; TTL is 7 days (a buyer
may open the order days later). Because the delivered email already contains the
codes, a 7-day token that re-displays those same codes on the web is not a broader
exposure than the email itself. The plaintext email rides the link (`&email=`) so
the order page can send it back as `X-Guest-Email`, matching the rest of the guest
surface; the token's hash is checked against it.

### Positive consequences

- The email-only `guest` token can no longer read codes; the IDOR is closed.
- No new friction for the happy path; no OTP state to store.
- The order-scoped token limits blast radius to a single order.

### Negative consequences

- The order page URL carries the access token (inherent to magic links) and the
  email; mitigate third-party leakage with a strict `Referrer-Policy`.
- The email-only `guest` token still authorises lower-sensitivity reads (order
  status, reviews); tightening those is tracked separately.

## Validation

- `tests/integration/test_guest_delivery_access.py`: the email-only token is
  rejected for codes; only an order-scoped token for the right order + email works;
  a token for another order or a mismatched hash is rejected; the resend endpoint
  is non-enumerating and mails only the order's address.
- `tests/unit/test_jwt.py`: `guest_order` round-trips and does not verify as `guest`.
