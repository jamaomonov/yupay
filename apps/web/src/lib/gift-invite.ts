/**
 * The pasted Steam invite link, as one identity: parse it, canonicalize it,
 * and decide whether a recipient verdict still applies to it.
 *
 * Framework-free, the way `player-check-state.ts` sits beside
 * `PurchasePanel`: two components need the same answers — `GiftRecipientField`
 * renders from them, and `GiftPurchasePanel` gates Buy on them — so neither
 * owns them. The Mini App keeps its twin (`validateInviteUrl`) in its own
 * `lib/gifts.ts` for the same reason.
 */
import type { GiftProfileCheck } from "./gifts";

//: Steam invite-link shapes, mirroring `checkout.py::parse_invite_url`'s
//: three accepted forms — this is only a client-side gate (the server is
//: the actual source of truth and canonicalizes on its own), so it doesn't
//: need to match byte-for-byte, just reject the same obviously-wrong input.
const STEAM_ID64_RE = /^\d{17}$/;
const STEAM_VANITY_RE = /^[A-Za-z0-9_-]{2,32}$/;
const S_TEAM_PATH_RE = /^[A-Za-z0-9/_-]{1,64}$/;

/** Turns whatever the buyer pasted into a `URL`, defaulting the scheme to
 *  `https://` the way a browser address bar would — shared by
 *  `canonicalInviteUrl` (which is both the accept/reject gate and the
 *  recipient check's key) and the "Открыть профиль" link (which needs the
 *  same normalized, absolute form to link to). */
function parseInviteUrl(raw: string): URL | null {
  const value = raw.trim();
  if (!value) return null;
  const candidate = value.includes("://") ? value : `https://${value}`;
  try {
    return new URL(candidate);
  } catch {
    return null;
  }
}

/**
 * The one identity a pasted link stands for: `https://` forced, host
 * lower-cased, trailing slashes gone. `null` when it isn't an accepted Steam
 * link at all.
 *
 * Two callers need this to be one function rather than two (2026-09-04 review
 * round 1). The recipient check files its verdict under this string, so
 * `steamcommunity.com/id/neo` and `https://steamcommunity.com/id/neo/` share
 * a verdict — keying on the raw field text instead let a buyer clear a
 * `not_found`, the single verdict allowed to block a purchase, by deleting a
 * trailing slash. And `isValidInviteUrl` is just "did this resolve to
 * something", so the accept/reject gate cannot drift from what gets checked.
 *
 * Mirrors `validateInviteUrl` in the Mini App's `lib/gifts.ts` exactly.
 */
export function canonicalInviteUrl(raw: string): string | null {
  const url = parseInviteUrl(raw);
  if (!url) return null;
  if (url.protocol !== "https:") return null;
  const host = url.hostname.toLowerCase();
  const parts = url.pathname.replace(/\/+$/, "").split("/").filter(Boolean);
  if (host === "steamcommunity.com") {
    if (parts.length === 2 && parts[0] === "profiles" && STEAM_ID64_RE.test(parts[1] ?? "")) {
      return `https://steamcommunity.com/profiles/${parts[1] ?? ""}`;
    }
    if (parts.length === 2 && parts[0] === "id" && STEAM_VANITY_RE.test(parts[1] ?? "")) {
      return `https://steamcommunity.com/id/${parts[1] ?? ""}`;
    }
    return null;
  }
  if (host === "s.team") {
    const tail = parts.slice(1).join("/");
    if (parts.length >= 2 && parts[0] === "p" && S_TEAM_PATH_RE.test(tail)) {
      return `https://s.team/p/${tail}`;
    }
    return null;
  }
  return null;
}

export function isValidInviteUrl(raw: string): boolean {
  return canonicalInviteUrl(raw) !== null;
}

/** The "Открыть профиль получателя" link's `href` — the normalized,
 *  absolute form of the pasted invite, or `null` while it isn't a valid one
 *  yet. This is the free half of the deferred server-side profile checker:
 *  the buyer verifies the link resolves to the right person with their own
 *  eyes, in a new tab, before paying (2026-09-04 review). */
export function inviteProfileHref(raw: string): string | null {
  if (!isValidInviteUrl(raw)) return null;
  return parseInviteUrl(raw)?.toString() ?? null;
}

/** One recipient-check verdict, kept together with the profile it was asked
 *  about — `canonicalUrl`, never the raw field text (see `currentVerdict`). */
export interface RecipientVerdict {
  canonicalUrl: string;
  check: GiftProfileCheck;
}

/**
 * The verdict that currently applies to `inviteUrl`, or `null` when none
 * does.
 *
 * A stored verdict is read back only while the field still points at the
 * same profile it was asked about — which buys two things at once: aiming the
 * field at someone else resets the check with no effect to keep in sync, and
 * an answer that lands after the buyer has already corrected the link is
 * discarded rather than shown against a profile they no longer mean.
 *
 * Keyed on `canonicalInviteUrl`, never the raw field text: a cosmetic edit
 * that resolves to the same profile must not discard the verdict — otherwise
 * a buyer clears a `not_found`, the single verdict allowed to block a
 * purchase, by deleting a trailing slash.
 */
export function currentVerdict(
  verdict: RecipientVerdict | null,
  inviteUrl: string,
): GiftProfileCheck | null {
  if (verdict === null) return null;
  const canonical = canonicalInviteUrl(inviteUrl);
  return canonical !== null && verdict.canonicalUrl === canonical ? verdict.check : null;
}
