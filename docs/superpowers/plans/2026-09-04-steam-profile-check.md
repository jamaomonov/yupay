# Steam Gifts — recipient profile check (avatar + nickname)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Branch: `main` (LIVE on prod).

**Goal:** Before paying, the buyer presses «Проверить» next to the Steam profile link and sees the recipient's avatar and nickname — so a mistyped link stops being an unrecoverable, paid mistake.

**Architecture:** Server-side, through Steam's documented Web API with our existing key. A browser cannot do this: Steam sends no CORS headers for our origin, so a client-side `fetch` can issue the request but never read the response. We already call `GetPlayerSummaries` server-side for Steam sign-in, the Web API allows 100k calls/day, and this feature adds at most a few thousand — with a Redis cache making repeats free. Proxies solve a problem we do not have at this volume.

**Spec:** operator request (2026-09-04), closing the UI/UX review's "no confirmation of who the link points to" finding.

## Global Constraints

- **The check must never be the reason a sale fails when the failure is ours.** Gate the purchase only on a definitive negative — "we asked Steam and this profile does not exist". An unset API key, a Steam outage, a timeout, or an unsupported link type must all leave the buyer free to continue.
- Recipient identity is PII: the steamid, nickname and avatar must never reach the structured logs (the existing redactor already covers `player_id`-class fields — treat these the same).
- The endpoint is public and proxies a third party: it needs its own `guard_ip` rate-limit bucket and a Redis cache (profiles change rarely — 6 h is generous).
- Behind `STEAM_GIFTS_ENABLED` like the rest of the gifts surface.
- mypy --strict, ruff, Google docstrings (backend); TS strict, no `any` (frontends). Every string in ru + en + uz.
- Miniapp tests are node-env with NO jsdom/RTL — export pure helpers and test those.
- Conventional Commits; do NOT push, do NOT deploy. **Never run `git stash`/`git checkout` on the worktree** (use `git show HEAD:<path>` to inspect a pristine file). Never stage the pre-existing dirty files.

---

### Task P1: Backend — the lookup endpoint

**Files:** `apps/api/src/yupay/modules/gifts/profile.py` (new), `routes.py`, `schemas.py`, `apps/api/src/yupay/modules/auth/steam.py` (reuse/relocate `fetch_persona`), `docs/architecture/cache-keys.md`, tests.

**Endpoint:** `POST /api/v1/gifts/steam-profile` with a `{invite_url}` body → `GiftProfileOut`
(planned here as a `GET` with a query parameter; changed during P2's review — `Caddyfile.prod`
logs each request's `uri`, query string included, and promtail ships that to Loki, so a query
parameter would have logged a _recipient's_ Steam identity):

```python
class GiftProfileOut(BaseModel):
    status: Literal["found", "not_found", "unsupported", "unavailable"]
    steam_id: str | None      # resolved steamid64
    nickname: str | None
    avatar_url: str | None
```

**Resolution:**

- `steamcommunity.com/profiles/{17 digits}` → the id is in the URL, no resolve call needed.
- `steamcommunity.com/id/{vanity}` → `ISteamUser/ResolveVanityURL/v1/`; a `success != 1` answer is `not_found`.
- `s.team/p/...` → `unsupported`: these are friend-invite tokens, not profiles, and the Web API cannot resolve them. Say so in the copy rather than pretending the check failed.
- Then `GetPlayerSummaries` for nickname + `avatarfull`. `fetch_persona` in `auth/steam.py` already does exactly this and already degrades to `(None, None)` — reuse it; if it needs to live somewhere shared, move it and keep the auth import working.
- No `steam_api_key` configured, any transport error, or a Steam 5xx → `unavailable`. Never a 500, never an exception out of the handler.

Reuse `parse_invite_url` from `gifts/checkout.py` so the endpoint accepts exactly the shapes checkout accepts — a link that passes here must never be rejected at checkout, and vice versa.

**Cache:** `gifts:steam_profile:{steamid_or_vanity}` for 6 h, documented in `docs/architecture/cache-keys.md`. Cache `found` and `not_found`; never cache `unavailable` (it is our failure, not a fact about the profile).

**Steps:** tests first (respx-mocked Steam) — a `/profiles/` link returns found with nickname+avatar and makes no resolve call; a vanity link resolves then summarises; an unknown vanity is `not_found`; an `s.team` link is `unsupported` with no Steam call at all; a missing API key is `unavailable`; a Steam timeout is `unavailable`; the flag being off 404s like the rest of the router; a second identical call is served from cache. → fail → implement → pass → `uv run pytest apps/api/tests -k "gift or profile" -q`, ruff, `uv run mypy apps`, then `make gen-api` and commit `docs/api/openapi.json` (new endpoint — the `openapi-drift` CI gate fails otherwise). Commit `feat(api/gifts): resolve a recipient's Steam profile for the pre-purchase check`.

---

### Task P2: Web — the check button and the resolved card

**Files:** `apps/web/src/components/gifts/GiftPurchasePanel.tsx`, `apps/web/src/lib/gifts.ts`, `packages/i18n/locales/{ru,en,uz}/web.json`, tests.

**Reference implementation:** `apps/web/src/components/store/PurchasePanel.tsx`'s `CheckablePlayerField` (~:133) already does this job for game player IDs — it owns its own check state and collapses into a confirmed pill showing the nickname and the id it resolved to. Match its behaviour and its states; add the avatar, which gifts have and it does not.

**Behaviour:**

- A «Проверить» button sits next to the invite field, enabled once the link parses.
- `found` → the field collapses into a card: avatar (48 px, `next/image` unoptimised — `avatars.steamstatic.com` is a third-party host, see `lib/image.ts::isOptimizable`), nickname, and a «Изменить» control that reopens the field.
- `not_found` → visible error next to the field: the profile does not exist. **This is the one state that blocks Buy.**
- `unsupported` / `unavailable` → a neutral, non-alarming note («ссылку этого вида проверить нельзя» / «Steam сейчас не отвечает — можно продолжить») and the purchase stays available.
- Editing the link resets the check.
- `canBuy` gains exactly one new condition: not `not_found`. Everything else leaves it untouched.
- The CTA hint (added in the C2 task) gains a matching branch so an unchecked link reads as the next step rather than a dead button.

**Steps:** tests first (found → card with nickname and avatar; not_found → error and Buy disabled; unavailable → note and Buy still enabled; editing the link resets) → fail → implement → pass → web suite, `tsc --noEmit`, lint, locale parity. NEVER `next build` on the host. Commit `feat(web): check the recipient's Steam profile before paying`.

---

### Task P3: Miniapp — the same, adapted

**Files:** `apps/miniapp/src/components/gifts/GiftBuyPanel.tsx`, `apps/miniapp/src/pages/GiftGame.tsx`, `apps/miniapp/src/lib/gifts.ts`, `packages/i18n/locales/{ru,en,uz}/miniapp.json`, tests.

Same states and the same "only a definitive negative blocks Buy" rule. Use `SafeImage` (`components/ui/safe-image.tsx`) for the avatar — it already handles a failing third-party image. Extract the state decision (`profileCheckState({status, linkChanged, …})` or similar) as an exported pure helper and unit-test it, mirroring how `walletPayState` and `walletSubmitReady` are tested — this app cannot render in tests.

**Steps:** as P2, plus confirming TopUp stays green if anything shared is touched. Commit `feat(miniapp): check the recipient's Steam profile before paying`.
