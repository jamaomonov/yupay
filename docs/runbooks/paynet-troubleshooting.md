# Runbook — Paynet

Two halves. We build a **deep link** that opens the Paynet app with the order
pre-filled, and Paynet settles it by calling our **UWS JSON-RPC endpoint**.
Design: [ADR-0078](../decisions/0078-paynet-acquirer.md). Protocol detail:
`apps/api/src/yupay/modules/paynet/README.md`.

## Turning it on

In `secrets/api.env` on the VPS:

```
PAYNET_USERNAME=paynet
PAYNET_PASSWORD=<the password we issued to Paynet>
PAYNET_SERVICE_ID=<the number in Table 3 of the contract annex>
PAYNET_PAY_URL_TEMPLATE=<the link format Paynet supplies>
```

then `docker compose -f docker-compose.prod.yml up -d --force-recreate api`.
A plain `restart` does **not** re-read `env_file`.

With either credential empty the method does not appear at checkout and the
endpoint answers 401 to everything — a half-configured deployment cannot take
money it has no way to settle.

## The link format is expected to be wrong at first

`PAYNET_PAY_URL_TEMPLATE` is a format string, not a URL, precisely because
Paynet hands over the real one after integration. Placeholders:

| Placeholder      | Value                       |
| ---------------- | --------------------------- |
| `{service_id}`   | `PAYNET_SERVICE_ID`         |
| `{account}`      | our order id                |
| `{amount}`       | the charge in **tiyin**     |
| `{amount_major}` | the same charge in **soʻm** |

Correcting it is an env edit plus `up -d --force-recreate api`. No release, no
deploy. If a template names a placeholder that is not in that table, intent
creation fails with `paynet_pay_url_template has an unknown placeholder` rather
than a `KeyError` — that message names the typo.

## Reading a failure

Everything except an auth failure is an HTTP 200 carrying a JSON-RPC `error`.
Grep the api logs for `paynet.`:

| Line / code                               | Means                                                                                                                                    |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| HTTP 401, no body                         | Wrong or missing Basic credentials. Check the env pair                                                                                   |
| `305`                                     | Their call carried a `serviceId` that is not ours                                                                                        |
| `302`                                     | The `order_id` in the link does not exist — **or** `GetInformation` on an order already paid (302 there, not 201: see the module README) |
| `201`                                     | `PerformTransaction`: a duplicate tap (new `transactionId`, order already paid) **or** an exact replay (same `transactionId` sent twice) |
| `501`                                     | The order expired or was cancelled before they called                                                                                    |
| `413` + `paynet.amount_mismatch`          | Amount ≠ the order's charge. The log line has both figures                                                                               |
| `203`                                     | Cancel for a transaction we never performed                                                                                              |
| `306` + `paynet.cancel_refused_delivered` | Reversal refused: goods already handed over                                                                                              |
| `414`                                     | `GetStatement` window is not `YYYY-MM-dd HH:mm:ss`                                                                                       |
| `-32600` / `-32601`                       | Their envelope or method name. Ours to report, not to fix                                                                                |
| `paynet.uws.internal_error`               | We broke. Read the traceback above it                                                                                                    |

Where a payment stands:

```sql
SELECT t.paynet_transaction_id, t.provider_trn_id, t.state, t.amount_tiyin,
       o.status AS order_status, t.performed_at, t.cancelled_at
FROM paynet_transactions t JOIN orders o ON o.id = t.order_id
ORDER BY t.performed_at DESC LIMIT 20;
```

`state` is `1` successful, `2` cancelled. There is no third stored value: an id
we have never seen is the absence of a row, and `CheckTransaction` answers `3`
for it.

## Things that will come up

**"Paynet says we are slow."** Their SLA is 500 ms per transaction, one second
in exception, and they cut the connection at 30 s — systematic breaches let
them disable the supplier. Nothing on this path calls an upstream, so a slow
response means the database. Check the api logs for the request duration and
`pg_stat_activity` before assuming it is them.

**"A customer paid and the order is still unpaid."** Look for their
`PerformTransaction` in the api log. If it never arrived, the money is on
Paynet's side and has not reached us — reconcile with their register. If it
arrived and errored, the code in the table above says why.

**"They ask us to cancel a delivered order."** We refuse with `306` on purpose:
the customer holds the code, and a reversal would hand them the goods for free.
This is settled by a human — refund from the admin panel after deciding, or
decline.

**"Reconciliation does not match."** `GetStatement` returns **successful
transactions only**; a cancelled row would read as money we claim to hold and
do not. Their register of accepted payments is the right thing to compare it
against.

**Rotating the password.** Edit `secrets/api.env`, recreate the api container,
tell Paynet. There is no `ChangePassword` endpoint and there will not be one —
letting a counterparty rewrite our credential store buys nothing.

## Known gaps

- **No merchant-initiated refund.** The admin refund button refuses on a Paynet
  payment; a reversal starts on their side and arrives as `CancelTransaction`.
  Same as Payme.
- **The deep link Paynet gave us cannot carry an order.** They answered
  `https://app.paynet.uz/?m=merchant_id` (2026-09-22): merchant only, no
  account, no amount. The payer would have to type our `order.id` — a UUID —
  into their app. `PAYNET_PAY_URL_TEMPLATE` therefore stays unset, the gateway
  stays `available=False`, and Paynet does not appear at checkout. Unblocking
  it needs Paynet either to accept the account as a link parameter or to agree
  a short public order number, which is a schema change on our side. See the
  module README, "The link format is expected to be wrong at first".
- **`transactionState` is unresolved.** We send it as a JSON number (`1`, `2`,
  `3`). Asked whether it should become a string like `status` did, Paynet
  answered _"не нужно менять пусть остается строкой"_ — which says both "leave
  it" and "as a string", and it is not a string today. Do not change it on
  that sentence alone; get a yes or no first. Certification passed with the
  number, so the number is the safer default meanwhile.

## The IP allowlist

Live since 2026-09-22. `infra/caddy/Caddyfile.prod` restricts
`/api/v1/payments/paynet/uws` to the seven addresses Paynet gave us:

```
109.207.244.62   62.209.139.94   109.207.244.94   89.236.220.222
91.196.76.52     94.158.63.240   195.158.21.42 (test)
```

Individual hosts, not a range. Basic auth stays the real control; this is
depth, the same shape as Payme's block directly above it in the file.

**195.158.21.42 is their test address and should come out once Paynet signs
the integration off.** Edit the Caddyfile, then
`docker compose -f docker-compose.prod.yml up -d --force-recreate caddy` — a
plain `caddy reload` re-reads the stale inode behind the bind mount and
reports "config is unchanged".

If genuine Paynet calls start 403ing, this matcher is the first suspect:
`client_ip` resolves through the shared edge proxy and Cloudflare, so a change
to either can hand Caddy the wrong address. The Payme comment in the same file
explains that chain.

- **The link format is unverified** until the first sandbox payment.
