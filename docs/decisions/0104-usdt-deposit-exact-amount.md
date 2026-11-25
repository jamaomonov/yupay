# 0104. USDT deposit top-up (TRC20, BEP20, ERC20): one address per chain, exact amounts, chain polling

- **Status**: Accepted
- **Date**: 2026-11-11
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | merchants

## Context and problem statement

Resellers top up the USD deposit by card transfer (ADR-0094) or through support. Several of
them hold USDT and ask to pay in it. The owner wants the deposit credited without anyone
reading a wallet by hand, and without a fee eating the 7–8 % margin.

## Considered options

1. **One owner wallet, exact-amount reservations, poll the chain** — chosen.
2. **A deposit address per reseller from a custodial API** (Pretixe and similar). There is no
   amount to match, but the keys sit with a third party, every address must be swept to one
   wallet, and each sweep costs Tron energy (~$1–8). The webhook signature is undocumented,
   so we would verify each transfer on the chain anyway.
3. **A hosted crypto gateway** (NOWPayments, Plisio and similar). 0.5–1 % per payment, plus a
   third party holding the money until payout.

## Decision outcome

**Chosen option:** 1. It is the ADR-0094 pattern with the chain as the notification source.

- **Wallets.** One owner address per chain, in `usdt_networks` with its own on/off switch:
  TRON for TRC20, and a `0x` address for BEP20 and ERC20 (the same one can serve both). Only
  public addresses are stored; the keys never touch our systems. The admin refuses an
  address whose checksum fails: base58check on TRON, EIP-55 on EVM chains. An all-lowercase
  `0x` address carries no checksum and is refused. The reseller picks the chain after the
  amount, as on FZR. Amounts are held per chain, so 100.00 can be open on TRON and on BNB
  Chain at once.
- **Reservation.** The reseller enters a USD amount. If it is free, we hold exactly that
  amount for 30 minutes:
  - A partial unique index makes "one open amount" a database rule.
  - An expired, cancelled or paid amount stays held for 60 more minutes.
  - One merchant may open 10 reservations an hour.

  If another reservation holds the amount, nothing is held. The answer is
  `409 usdt_amount_taken` with a free `suggested` amount (the request plus random cents),
  and the reseller either continues with it or changes the amount (owner's rule,
  2026-11-11).

  The trade-off was weighed against the review's proposal to always add cents. A round
  transfer sent without reserving, or rounded by an exchange, can pay whoever holds that
  exact round amount. The 5-second window and the hourly cap keep that to a reseller's own
  mistake on an amount someone else reserved first.

- **Intake, BEP20 / ERC20 (added 2026-11-11).** The same job reads plain JSON-RPC:
  - It calls `eth_getLogs` for the USDT contract's `Transfer` event with our address as the
    indexed recipient, and reads only blocks buried 20 deep (BNB Chain, ~15 s) or 12 deep
    (Ethereum, ~2.5 min).
  - Each log is re-checked: emitting contract, topic, recipient, and not `removed`.
  - The block time comes from the block itself. An event is `(tx, log index)`.
  - The node URLs are settings (`BSC_RPC_URL`, `ETH_RPC_URL`), with public keyless defaults.
  - USDT on BNB Chain has 18 decimals, so the journal keeps 18.
- **Intake, TRC20.** A scheduler job polls TronGrid every 20 s for confirmed TRC20 transfers to the
  address. It keeps a transfer only if:
  - the contract is the official USDT (`TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t`);
  - the recipient is our address;
  - the type is `Transfer` and the token has 6 decimals.

  A fake token named "USDT" never matches. Zero-value and dust transfers (under 1 USDT,
  the address-poisoning spam) are never journaled. An event is
  `(tx_id, sender, amount)`, journaled once; one transaction can carry several.

- **Matching.** The amount and the address equal the reservation's, and the block time falls
  inside its window, `[created_at − 5 s, closed_at or expires_at]`.
  - Two windows for the same amount never overlap, because the amount stays held 60 minutes
    after closing, so at most one reservation can match.
  - The block time comes from the chain, so a transfer found late (the poller was down)
    still pays the reservation it was made for.
  - The window opens only seconds before the reservation existed. The address is public and
    a block is visible about a minute before it is confirmed; a wider grace let a reseller
    reserve an amount after seeing someone else's transfer land, and be credited for it
    (security review, 2026-11-11).
- **Too fast to be honest.** A transfer mined sooner after its reservation than the network's
  lead is not credited automatically but goes to the operator (`intake._MIN_LEAD`): a free
  amount is reserved exactly as asked and a pending transfer is public before its block, so
  someone watching the address could reserve the amount of another person's unreserved
  transfer. The lead only has to outlast that public window: 10 s on BEP20 and TRC20 (~3 s
  blocks), 60 s on ERC20. It was a flat 60 s until 2026-11-25, when an honest BEP20 deposit
  landed inside it.
- **Credit.** `merchants.deposit.credit_deposit`, 1 USDT = 1 USD, idempotency key
  `usdt:{reservation.id}`.
- **Unmatched.** A transfer that matches nothing lands `unmatched` in the journal and sends
  an admin alert. In the admin, the operator either credits it to a reseller (key
  `usdt:incoming:{id}`) or dismisses it. Transfers under 1 USDT are dust (address poisoning)
  and are journaled `ignored` with no alert.

### Positive consequences

- No per-payment fee, no sweeping, no third party holding money.
- Nothing to forge on our side: no inbound webhook, and the chain is the source of truth.
- Most of the shape and the tests reuse ADR-0094.

### Negative consequences

- **Mempool view of an unreserved transfer.** A transfer that matches no hold (a mistake, a
  late payment, other income) can be claimed by someone who sees it pending and reserves that
  amount first. Reserved amounts are safe, held by the unique index. Hence: dedicated
  addresses (runbook §1).
- **Fixed confirmation depth, not finality.** 12 blocks on Ethereum and 20 on BNB Chain; a
  deeper reorg is not handled. Reading up to the node's `finalized` block would close it at
  the cost of ~13 min on Ethereum.

- The reseller must send the exact amount. An exchange that deducts its withdrawal fee from
  the amount sent produces an unmatched transfer, which is credited by hand.
- **TronGrid dependency.** We trust TronGrid's answer over HTTPS. An outage delays credits
  but loses nothing:
  - The next poll reads from the stored cursor minus 10 minutes, and the event key makes the
    overlap harmless.
  - A poll that hits the page cap resumes exactly where it stopped, so a spam flood cannot
    pin the cursor.
  - The cursor never passes "now" or a transfer that failed to ingest.
  - Any failure lasting 15 minutes alerts.
- **Legal status of USDT receipts** for the owner's entity is an open question for the tax
  consultant. The feature ships with `mode = off`.

## References

- ADR-0094 (P2P card deposit), whose reservation rules this copies.
- Module: `apps/api/src/yupay/modules/usdt/README.md`
- Runbook: `docs/runbooks/usdt-deposit.md`
