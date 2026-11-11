# Runbook: USDT deposit top-up (TRC20, BEP20, ERC20)

ADR-0104. Resellers send an exact USDT amount to the owner's address on the chain they
picked. The scheduler's `usdt_poll` job credits it after confirmation:

- TRON: about a minute;
- BNB Chain: under 30 s;
- Ethereum: about 3 minutes.

## 1. Go-live

1. **Ask the consultant first.** Receiving USDT on the owner's entity is an open legal
   question. Until it is answered, keep `mode = off`.
2. **Create wallets whose keys only the owner holds.** Use Trust Wallet, TronLink or a
   hardware wallet, not an exchange deposit address. An exchange can change its addresses, and
   it credits by its own rules.
   - **TRON.** The address starts with `T`. Activate it: it needs at least one incoming
     transfer of TRX or USDT.
   - **BNB Chain and Ethereum.** The `0x` address can be the same for both. Copy it as the
     wallet shows it, with capital letters: that is its checksum, and the admin refuses an
     all-lowercase one.
3. **Optional: a TronGrid API key.** Put it in `secrets/api.env` as `TRONGRID_API_KEY`, then
   recreate `scheduler` with `IMAGE_TAG` set.
4. **Set each chain in the admin.** Go to USDT → Settings → Сети. For each chain, paste its
   address, check it character by character against the wallet, switch it on and save. The
   form refuses a broken checksum, but not someone else's valid address. A chain reads
   nothing before the moment its address was saved.
   - **Optional: own nodes.** The BEP20 / ERC20 nodes default to public keyless ones. A
     provider's URL can go into `BSC_RPC_URL` / `ETH_RPC_URL` in `api.env`.
5. **Test with the owner's own merchant.** Set `mode = allowlist`, top up 10 USDT from
   another wallet and wait for "Оплачено" in the cabinet. Check that the journal row shows
   `matched` and the deposit grew by 10.00.
6. **Open to everyone** with `mode = all`.

## 2. An unmatched transfer (alert `usdt_unmatched`)

Usual causes:

- an exchange deducted its fee, so 99.00 arrived instead of 100.00;
- the reseller sent after the 30 minutes ran out;
- the reseller sent without opening a top-up.

What to do:

1. Open USDT → Journal → «Неопознанные». The sender's address and the transaction link go
   to Tronscan.
2. Find the reseller, usually from their message in support.
3. Choose «Зачислить», pick the reseller and add a note. This books the amount rounded down
   to cents, once only (key `usdt:incoming:{id}`).
4. If it is not a top-up, return it from the wallet and choose «Закрыть без зачисления» with
   a note.

## 3. Nothing is credited (alert `usdt_poll_down` / `usdt_ingest_failed`, or resellers complain)

1. Check the scheduler logs for `usdt_poll.tron_unavailable`, `usdt_poll.failed` or
   `usdt.ingest_failed` (that one names the transaction the cursor is waiting on).
2. **TronGrid down or rate-limited.** Credits catch up by themselves when it returns: the
   poll re-reads from the cursor and matches by block time. Adding `TRONGRID_API_KEY` lifts
   the rate limit.
3. **The transfer is visible on Tronscan but not in the journal.** Check that its contract
   is Tether's (`TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t`) and that its recipient is the address
   in Settings. A fake "USDT" is never journaled on purpose.

## 4. Changing the address

Save the new address in Settings. The cursor resets to "now", so the new address's history
is ignored.

Saving closes every pending reservation, because those show the **old** address and the
poller no longer reads it. A reseller who already sent to the old address is credited by
hand: find the transfer on Tronscan, then use the admin's deposit credit with a note. Do the
change when nothing is pending if you can.

## 5. Turning it off

Set `mode = off`. The cabinet hides the method. The poller keeps reading until every
reservation's amount is released (up to two hours), so a reseller who already sent is still
credited.
Credits from the journal stay as they are.
