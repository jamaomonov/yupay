# Runbook: USDT (TRC20) deposit top-up

ADR-0104. Resellers send an exact USDT amount on TRON to the owner's address. The
scheduler's `usdt_poll` job credits it within about a minute of confirmation.

## 1. Go-live

1. **Ask the consultant first.** Receiving USDT on the owner's entity is an open legal
   question. Until it is answered, keep `mode = off`.
2. **Create a wallet whose keys only the owner holds.** Use TronLink or a hardware wallet,
   not an exchange deposit address. An exchange can change its addresses, and it
   credits by its own rules. Activate the address: it needs at least one incoming transfer of
   TRX or USDT.
3. **Optional: a TronGrid API key.** Put it in `secrets/api.env` as `TRONGRID_API_KEY`, then
   recreate `scheduler` with `IMAGE_TAG` set.
4. **Set the address in the admin.** Go to USDT → Settings, paste the address and check it
   character by character against the wallet. The form refuses a broken checksum, but not
   someone else's valid address.
5. **Test with the owner's own merchant.** Set `mode = allowlist`, top up 10 USDT from
   another wallet and wait for "Оплачено" in the cabinet. Check that the journal row shows
   `matched` and the deposit grew by 10.00.
6. **Open to everyone** with `mode = all`.

## 2. An unmatched transfer (alert `usdt_unmatched`)

Usual causes:

- an exchange deducted its fee, so 99.00 arrived instead of 100.00;
- the reseller sent after the 60 minutes ran out;
- the reseller sent without opening a top-up.

What to do:

1. Open USDT → Journal → «Неопознанные». The sender's address and the transaction link go
   to Tronscan.
2. Find the reseller, usually from their message in support.
3. Choose «Зачислить», pick the reseller and add a note. This books the amount rounded down
   to cents, once only (key `usdt:incoming:{id}`).
4. If it is not a top-up, return it from the wallet and choose «Закрыть без зачисления» with
   a note.

## 3. Nothing is credited (alert `usdt_poll_down`, or resellers complain)

1. Check the scheduler logs for `usdt_poll.tron_unavailable` or `usdt_poll.failed`.
2. **TronGrid down or rate-limited.** Credits catch up by themselves when it returns: the
   poll re-reads from the cursor and matches by block time. Adding `TRONGRID_API_KEY` lifts
   the rate limit.
3. **The transfer is visible on Tronscan but not in the journal.** Check that its contract
   is Tether's (`TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t`) and that its recipient is the address
   in Settings. A fake "USDT" is never journaled on purpose.

## 4. Changing the address

Save the new address in Settings. The cursor resets to "now", so the new address's history
is ignored.

Reservations still pending keep the **old** address, and the poller no longer reads it. Do
the change when nothing is pending, or credit transfers to the old address by hand from
Tronscan.

## 5. Turning it off

Set `mode = off`. The cabinet hides the method and the poller stops reading the chain.
Credits from the journal stay as they are.
