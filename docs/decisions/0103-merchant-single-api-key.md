# 0103. One API key for the merchant API, and one IP allowlist per merchant

- **Status**: Accepted
- **Date**: 2026-11-09
- **Deciders**: @jamaomonov
- **Tags**: backend | merchants | security

## Context and problem statement

To integrate with `/merchant/v1`, a reseller had to copy three values:

- a key id (`ypm_…`);
- a request-signing secret (`ypms_…`);
- a webhook secret (`ypmw_…`).

They also had to implement the HMAC canonical string (spec §9.2) in their own
language. All three values start with `ypm`, and one integration put every
value in the wrong slot. A sister project, csmarket, integrates with one bearer
token and nothing else, and resellers compare the two.

The IP allowlist was fixed per key when the key was issued. On 2026-11-05 a
reseller's new server called us over IPv6 while its key only listed the IPv4
address, so every request got `403 ip_not_allowed`. Adding the address meant
issuing a new key and redeploying.

The owner asked for one value to integrate with, one allowlist that applies to
every key and can be edited, and no change for resellers already integrated.

## Considered options

1. **A bearer key, alongside the signed scheme.**
   - New keys are one string, `ypk_` + 32-character public id + 43-character
     secret, sent as `Authorization: Bearer`.
   - Old `ypm_`/`ypms_` keys keep the HMAC scheme, untouched.
   - Webhooks are also signed with each live `ypk_` key.
2. **Bearer only, and migrate everyone.** Every integrated reseller would have to
   redeploy. This fails the owner's constraint.
3. **Keep HMAC, and hand out `key_id.secret` as one string.** One value to paste,
   but the integrator still has to implement the canonical string. That code is
   where the real integration cost is.

## Decision outcome

**Option 1.**

### Key format

- **Storage.** The `ypk_` key lives in the existing `merchant_api_keys` row:
  - `key_id` is the first 36 characters, the public half;
  - `secret_enc` is the rest, encrypted exactly like a `ypms_` secret.
    No new column, and revocation, `last_used_at`, the per-key rate counter and
    the cabinet list all work unchanged.
- **Verification.** `auth._verify_bearer` looks up the key and compares the
  secret in constant time. An unknown or revoked key, or one that is not shaped
  like a `ypk_` key at all, is compared against a dummy, so all failures return
  the same 401 and cost the same, as on the signed path.
- **Optional HMAC.** A `ypk_` key can also sign requests on the old scheme:
  `key_id` is the id and the remainder is the secret. Nothing documents this;
  the test suite uses it.

### Webhooks

`X-Yupay-Key-Signature` signs the same canonical string as `X-Yupay-Signature`.

- It is keyed by each live `ypk_` key, newest first, comma-separated, so a
  rotation has no gap.
- `X-Yupay-Signature`, keyed by the `ypmw_` hook secret, is still sent on every
  delivery.
- The cabinet stops showing the hook secret when a URL is first set, and shows
  it only on «Сменить секрет».

### IP allowlist

- **One list per merchant.** The list moves to `merchants.api_ip_allowlist`, is
  edited in the cabinet (`PUT /merchant/cabinet/api-ip-allowlist`) and in the
  admin, and applies to every key.
- **Notification.** Editing the list mails the account. Widening it is the first
  thing an intruder in the cabinet would do.
- **Migration.** Migration 0109 backfills the merchant list from live keys:

  | Live keys                  | Merchant list          |
  | -------------------------- | ---------------------- |
  | all restricted             | union of their entries |
  | all open                   | no filter              |
  | some restricted, some open | no filter              |

  For the mixed case, restricting would lock the open key out of addresses
  nobody recorded. Leaving it open drops the filter on the restricted keys,
  which the key check still guards. On production that is one merchant out of
  nineteen.

- **Rollback.** `merchant_api_keys.ip_allowlist` stays in the table, unread, so
  rolling back to the previous image restores the per-key lists.

### Positive consequences

- A new integration is one header and one value. There is no clock and no
  canonical string to get wrong.
- Integrated resellers change nothing: same headers, same webhook header, same
  secret.
- Adding a server's IPv6 address is an edit, not a rotation.

### Negative consequences

- **Exposure of a captured request.** A bearer key in a captured request is the
  credential itself. A captured signed request is only replayable for ±300 s.
  - TLS covers transport.
  - Caddy redacts `Authorization` from the access log.
  - The key never reaches a browser.
  - This is the same trade csmarket, Stripe and GitHub make.
- **Two schemes to maintain.** The signed path stays until no live `ypm_` key is
  in use. `last_used_at` shows when that happens.
- **Broader filter for one merchant.** For a merchant whose keys had different
  lists, each key now accepts the union of the lists.

## Links

- Spec §9.2 (signed requests), §10 (webhooks): `docs/superpowers/specs/2026-09-06-merchant-b2b-design.md`
- `apps/api/src/yupay/modules/merchants/auth.py`, `signing.py`, `webhook_delivery.py`,
  `cabinet_key_routes.py`
- Migration `0109_merchant_api_ip_allowlist`
