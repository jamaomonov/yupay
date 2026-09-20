# 0085. Verifying a Telegram username, and doing it with no fallback

- **Status**: Accepted
- **Date**: 2026-09-20
- **Deciders**: owner, Claude
- **Tags**: backend | integrations

## Context and problem statement

Telegram Stars and Premium took a `username` and checked nothing. A typo was
discovered by the supplier, after payment — the failure mode every other
checked brand has had a guard against since [ADR-0031](./0031-storefront-player-check.md).

The plan was NOVA primary, G2B fallback. Reading both APIs inverted it:

- **NOVA cannot validate a Telegram username at all.** Its Fragment `quote`
  takes one and ignores it: on 2026-09-20 it priced `@zz_no_such_user_zz_41907`
  and echoed it back as `recipient`. It is a calculator. Their spec has two
  check endpoints, `steam-topup/check-login` and `topups/validate-id`, and
  neither knows Telegram.
- **G2B can.** `checkPlayerId` under its `Telegram` game answered
  `{"valid": "valid", "name": "Jam", "img_src": …}` for a real handle and
  `{"valid": "invalid"}` for a nonsense one, with or without the leading `@`.

An earlier reading said the opposite — that G2B could not check and NOVA
could. Both halves were wrong, and for instructive reasons: the G2B probe used
`@telegram` and `@durov`, a channel and an account that cannot receive a gift,
so a real verdict of "invalid" read as "unsupported"; and NOVA's quote was
taken for a validation because it accepts the field. Probe inputs that cannot
succeed prove nothing about capability.

## Decision

Check the Telegram username through **G2B only**, with no fallback, and enable
it by configuration.

### No new endpoint, and no fifth deviation

`POST /catalog/brands/{slug}/check-player` already exists and is already one of
the four advisory pre-purchase lookups AGENTS.md §10 names. Two more brands
reaching the same endpoint is not a fifth deviation, so §10's list is unchanged
— this ADR says so explicitly because the opposite was assumed for a day.

Enabling it is one field: `FormField.check = {"provider": "g2b"}` on each
product's `username`. The endpoint, cache, breaker, rate-limit bucket and
three-way `valid|invalid|error` shape are all the existing ones.

### A brand-keyed table for a brand we do not sell through G2B

`resolve_g2b_game_code` derived the game code from the brand's G2B mappings,
which quietly means "a brand can only be checked by a supplier we buy from".
Nobody chose that rule; it is how the lookup happened to be written, and Stars
is where it breaks: G2B sells Stars only in fixed packs, so it is deliberately
not a channel for the free-amount line the storefront renders — and its
`checkPlayerId` answers for that same username perfectly well.

So `G2B_VALIDATE_ONLY` maps a brand slug to a game code for validation alone,
mirroring `player_check_nova.NOVA_VALIDATE`, which is a code table for the same
reason: validation is brand-scoped where a mapping is SKU-scoped. `telegram-
premium` is **not** in it — it has a real G2B mapping on the same `Telegram`
game, and one source per brand means the live row wins.

### No fallback, and saying so

Every other checked brand degrades an `error` to a NOVA second opinion. This
one cannot, because NOVA has no answer to degrade to. A G2B outage therefore
means the field goes unchecked and the order proceeds — which is exactly
today's behaviour, so it is not a regression, but it is a gap and it is written
here rather than left to be discovered during one.

Closing it needs a second supplier that validates Telegram, or Telegram's own
API. Neither is in reach today.

## Consequences

- `telegram-premium` was live the moment the field was configured: it resolves
  its code from the G2B mapping added the same day. Verified on production —
  `{"status":"valid","name":"Jam"}`.
- `telegram-stars` answers `error` until this ships, because the table is code.
  That is the whole demonstration that the table is needed.
- The check is advisory, as ADR-0031 requires: `invalid` blocks Pay, `error`
  never does.
