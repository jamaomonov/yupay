/**
 * The pre-purchase recipient check for Steam gifts on the Mini App: "who
 * does this pasted link actually point at?".
 *
 * A gift goes to whoever the link resolves to and there is no undo once
 * G-Engine's bot sends the friend invite, so the buyer can press
 * «Проверить» and see the recipient's avatar and nickname before paying.
 *
 * Its own module rather than another section of `lib/gifts.ts` (which is
 * already past the repo's 300-LOC soft limit for TS) — and the same split
 * this app already uses for the top-up player check, where the request
 * lives in `player-check.ts` and the state decision in
 * `player-check-state.ts`. Both halves are here because the whole thing is
 * ~150 lines; the render decision is `profileCheckState`, exported pure
 * because this app's Vitest suite is node-env with no jsdom/RTL.
 *
 * Mirrors `apps/web/src/lib/gifts.ts`'s `checkGiftProfile` /
 * `profileCheckBlocks` on the storefront — same endpoint, same contract,
 * same refusal to let our own failure cost a sale.
 */

import type { MessageKey } from "@/lib/i18n";

import { apiPost } from "@/lib/api";

/** The four verdicts the endpoint can return (mirrors `GiftProfileOut`).
 *
 *  They are deliberately not equally weighted: only `not_found` — Steam
 *  itself answering that no such profile exists — is a fact about the
 *  recipient. `unsupported` (an `s.team` friend-invite token the Steam Web
 *  API cannot resolve at all) and `unavailable` (no API key, an outage, a
 *  timeout, our own 5xx) are facts about *us*, and must never stand between
 *  the buyer and Buy. See `profileCheckBlocks`. */
export type GiftProfileStatus = "found" | "not_found" | "unsupported" | "unavailable";

/** Wire shape of `GiftProfileOut` — see `yupay.modules.gifts.schemas`. */
interface GiftProfileWire {
  status: GiftProfileStatus;
  steam_id: string | null;
  nickname: string | null;
  avatar_url: string | null;
}

/** The verdict as the UI consumes it. `found` is narrowed to carry a real
 *  nickname so a confirmation card can never render around an empty name —
 *  the one shape of this feature that would be worse than not shipping it,
 *  since it reassures the buyer without having confirmed anything. */
export type GiftProfileCheck =
  | { status: "found"; nickname: string; avatarUrl: string | null }
  | { status: "not_found" | "unsupported" | "unavailable" };

/** How long the WebView waits on the check before calling it `unavailable`. */
const CHECK_TIMEOUT_MS = 8000;

/** Explicit bidi formatting/override controls: LRE/RLE/PDF/LRO/RLO
 *  (U+202A–U+202E) and the isolates LRI/RLI/FSI/PDI (U+2066–U+2069). */
const BIDI_CONTROLS = /[\u202A-\u202E\u2066-\u2069]/g;

/**
 * Strip bidi controls from a Steam persona name.
 *
 * The nickname is third-party text — a *recipient* picks it, and the buyer
 * has never seen it before. A name containing `U+202E` (RIGHT-TO-LEFT
 * OVERRIDE) visually reverses everything after it, so it can reorder text it
 * is rendered next to: in `ConfirmPaymentDialog` the nickname sits in the
 * same row as the profile link the buyer is being told to verify, one tap
 * before an irreversible payment. Stripping at this boundary rather than
 * isolating at each render site means every present and future place this
 * name appears (card, confirm dialog, live region) is safe by construction.
 *
 * Only the explicit override/isolate controls go: a genuinely Arabic or
 * Hebrew persona still renders right-to-left from its own characters'
 * directionality, which is what the bidi algorithm is for.
 */
function stripBidiControls(name: string): string {
  return name.replace(BIDI_CONTROLS, "").trim();
}

/**
 * Resolve a pasted Steam link into "who is this, actually?".
 *
 * **Never throws and never rejects.** Any failure — network, our own 5xx, a
 * 429, a 404 from an API build that predates the endpoint, a 422 for a link
 * the server parses more strictly than `validateInviteUrl` does — folds into
 * `unavailable`, which is non-blocking. That is the whole point: this check
 * is a second pair of eyes, and a check that fails on our side must not cost
 * a sale. The server holds the same line (see `yupay.modules.gifts.profile`),
 * so this is belt-and-braces, not the only guard.
 *
 * Public data about a link the buyer just typed, so `anonymous: true` — no
 * bearer token is attached to a call that does not need one. `POST` for what
 * is logically a read: the link identifies a *third party*, and Caddy's
 * access log records the query string verbatim on its way to Loki, so the
 * link travels in the body where nothing logs it (see `GiftProfileIn` on the
 * API side for the full reasoning).
 */
export async function checkGiftProfile(inviteUrl: string): Promise<GiftProfileCheck> {
  // A hung request would otherwise spin «Проверяем…» until the WebView's own
  // default gives up, minutes later. Buy stays enabled throughout, so no sale
  // is lost — but a buyer who assumes the check is mandatory waits for all of
  // it.
  //
  // 8 s sits just above the server's own ceiling on all its Steam work
  // (`_TOTAL_BUDGET_SECONDS`, 7 s) — deliberately, so this abort is the outer
  // bound rather than the inner one. It used to be reasoned about against the
  // server's *per-call* 5 s, which was wrong: the vanity path makes two
  // sequential Steam calls, so its worst case ran past 8 s and a slow-but-alive
  // Steam produced the one outcome that reasoning ruled out — the buyer told
  // «Steam не отвечает» while the server went on to finish and cache a `found`
  // (2026-09-04 final review; the server-side budget is the actual fix, this
  // is now a true backstop).
  //
  // `AbortController` + `setTimeout`, not `AbortSignal.timeout`: the latter
  // is missing before iOS 15.4, and there it would throw *before the request
  // was ever sent*, so every single «Проверить» would report «Steam сейчас не
  // отвечает» and the buyer would conclude our check is broken. The degrade
  // is safe in direction but total and silent, and a Telegram Mini App runs
  // inside whatever WebView the buyer's phone ships — a mass-market CIS
  // audience, with no browserslist floor anywhere in this repo ruling those
  // devices out. `AbortController` has been everywhere since iOS 12.
  const controller = new AbortController();
  const timer = setTimeout(() => {
    controller.abort();
  }, CHECK_TIMEOUT_MS);
  try {
    const out = await apiPost<GiftProfileWire>(
      "/api/v1/gifts/steam-profile",
      { invite_url: inviteUrl },
      { anonymous: true, signal: controller.signal },
    );
    if (out.status !== "found") return { status: out.status };
    // The API contract says `found` always carries a persona (it returns
    // `unavailable` when Steam gave it nothing to show). If that ever stopped
    // holding, a nameless "confirmation" is the worst answer available — so it
    // degrades to the non-blocking status rather than to a blank green card.
    // A name that was *only* bidi controls lands here too, for the same
    // reason: after stripping there is nothing left to show.
    const nickname = out.nickname ? stripBidiControls(out.nickname) : "";
    if (!nickname) return { status: "unavailable" };
    return { status: "found", nickname, avatarUrl: out.avatar_url };
  } catch {
    return { status: "unavailable" };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Whether a verdict stands between the buyer and Buy. Only a definitive
 * `not_found` does.
 *
 * Deliberately the opposite of `blocksCheckout` in `player-check-state.ts`,
 * where an *unchecked* id also blocks: there the check is a required gate on
 * a top-up that would otherwise go to the wrong account with no way back;
 * here it is an optional second look, and `null` (never checked) leaves the
 * purchase exactly as available as it was before the button existed.
 */
export function profileCheckBlocks(check: GiftProfileCheck | null): boolean {
  return check?.status === "not_found";
}

/** A stored verdict together with the link it was asked about. Kept as a
 *  pair so `profileCheckState` can discard an answer the field has since
 *  moved past — see its docstring. */
export interface GiftProfileResult {
  /** The **canonical** link the verdict answers for — `validateInviteUrl`'s
   *  output, the same string the server was asked about and the same one
   *  `handleBuy` bills. Deliberately not the raw field text: a cosmetic edit
   *  that resolves to the same profile (deleting a trailing slash, dropping
   *  the scheme) must not discard the verdict, since the one verdict allowed
   *  to block a purchase would then be dismissible by accident
   *  (2026-09-04 review round 1). The raw text stays for display only. */
  canonicalUrl: string;
  check: GiftProfileCheck;
}

export interface ProfileCheckState {
  /** The confirmed recipient, or `null`. Non-null exactly when the invite
   *  field should collapse into the confirmation card. */
  found: { nickname: string; avatarUrl: string | null } | null;
  /** i18n key of the one blocking verdict, rendered as a `role="alert"` —
   *  screen readers do announce that on insertion. `null` otherwise. */
  alertKey: MessageKey | null;
  /** i18n key of the advisory (non-blocking) note under the field, or the
   *  "you haven't pasted a link yet" hint. `null` when there is nothing to
   *  say. */
  noteKey: MessageKey | null;
  /** Whether the verdict stands between the buyer and Buy. */
  blocks: boolean;
}

/**
 * The check's entire render decision, derived from the raw state
 * `GiftGame` holds — pulled out pure so the state matrix is unit-testable
 * without rendering (this app's Vitest suite is node-env, no jsdom/RTL),
 * mirroring `walletPayState` / `giftPayHint`.
 *
 * The verdict is read back only while the field still points at the very
 * profile it was asked about, which buys two things at once: aiming the
 * field at someone else resets the check with no effect to keep in sync, and
 * an answer that lands after the buyer already corrected the link is
 * discarded rather than shown against a profile they no longer mean.
 *
 * That comparison is on the **canonical** link, not the raw field text
 * (2026-09-04 review round 1): `steamcommunity.com/id/neo/` and
 * `https://steamcommunity.com/id/neo` are one profile, and keying on the raw
 * string let a buyer clear a `not_found` — the single verdict allowed to
 * block a purchase — by deleting a trailing slash. `canonicalInvite === null`
 * (the field no longer parses at all) holds no verdict either way.
 *
 * `attempted` is «Проверить» having been pressed on a field with nothing in
 * it. Only that case needs saying: a *wrong* link already has the field's
 * own error, and announcing an empty field before the buyer has tried would
 * be noise. Mirrors `checkAttempted` on the web panel and `attempted` in
 * `CheckablePlayerField`.
 */
export function profileCheckState({
  result,
  canonicalInvite,
  inviteHasValue,
  attempted,
}: {
  result: GiftProfileResult | null;
  /** `validateInviteUrl(inviteUrl)` — the caller already has it. */
  canonicalInvite: string | null;
  /** Whether the field holds any non-whitespace text at all. */
  inviteHasValue: boolean;
  attempted: boolean;
}): ProfileCheckState {
  const check =
    result !== null && canonicalInvite !== null && result.canonicalUrl === canonicalInvite
      ? result.check
      : null;
  const found =
    check?.status === "found" ? { nickname: check.nickname, avatarUrl: check.avatarUrl } : null;
  const blocks = profileCheckBlocks(check);
  const alertKey: MessageKey | null = blocks ? "gifts.game.profileNotFound" : null;
  let noteKey: MessageKey | null = null;
  if (attempted && !inviteHasValue) {
    // «Проверить» pressed on an empty field: the field's own error cannot
    // speak for this case (it requires a non-empty value), so without this
    // the button is a silent no-op. Reuses the Buy button's own wording for
    // the same missing thing rather than forking a fourth sentence.
    noteKey = "gifts.game.payHintInvite";
  } else if (check !== null && !blocks && check.status !== "found") {
    // `found` says it in the card instead, and `not_found` in the alert —
    // neither is repeated here.
    noteKey =
      check.status === "unsupported"
        ? "gifts.game.profileUnsupported"
        : "gifts.game.profileUnavailable";
  }
  return { found, alertKey, noteKey, blocks };
}
