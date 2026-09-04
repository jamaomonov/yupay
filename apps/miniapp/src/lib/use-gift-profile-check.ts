/**
 * The pre-purchase recipient check («Проверить») as one hook: every piece of
 * React state the Steam-gift page holds for it — the stored verdict, the
 * in-flight flag, the empty-press flag, the double-submit guard, the haptic,
 * and the render decision `InviteField` consumes.
 *
 * Its own module because `GiftGame.tsx` is far past the repo's 300-LOC soft
 * limit for TS and this is the one self-contained thing in it: the only
 * input it takes from the page is the raw text of the invite field, plus one
 * callback into the field's own "touched" flag (see `onInvalidAttempt`),
 * which belongs to the *link error*'s display timing and not to this check.
 *
 * Both testable halves stay in `lib/gift-profile.ts` and are unit-tested
 * there directly — `checkGiftProfile` (the request, which never rejects) and
 * `profileCheckState` (the whole render decision). Nothing testable moved
 * here: this app's Vitest suite is node-env with no jsdom/RTL, so a hook
 * cannot be rendered in it, and this file is deliberately only the React
 * wiring around those two.
 */

import { useEffect, useRef, useState } from "react";

import type { GiftProfileResult, ProfileCheckState } from "@/lib/gift-profile";

import { checkGiftProfile, profileCheckState } from "@/lib/gift-profile";
import { validateInviteUrl } from "@/lib/gifts";
import { haptic } from "@/lib/telegram";

/** What `GiftGame` gets back — see each field on the hook below. */
export interface GiftProfileCheckHandle {
  /** Everything the check currently has to say about the link in the field —
   *  the confirmation card, the one blocking alert, the advisory note, and
   *  whether Buy is blocked at all. See `lib/gift-profile.ts`. */
  state: ProfileCheckState;
  /** A check request is in flight. */
  checking: boolean;
  /** «Проверить». Never rejects, which is what makes a bare `void check()`
   *  at the call site safe. */
  check: () => Promise<void>;
  /** Reopen the collapsed field from the card's «Изменить». */
  reopen: () => void;
  /** Call from the invite field's own change handler — the check's half of
   *  "the buyer edited the link". */
  onUrlChange: () => void;
}

/**
 * Wire up the recipient check for one invite field.
 *
 * The verdict is stored together with the link it was asked about and read
 * back only while the field still holds that same link (`profileCheckState`)
 * — editing the link resets the check with no effect to keep in sync, and an
 * answer that lands after the buyer already corrected the link is discarded
 * rather than shown against a profile they no longer mean.
 */
export function useGiftProfileCheck({
  inviteUrl,
  onInvalidAttempt,
}: {
  /** The raw text of the invite field. Canonicalised here with the same
   *  `validateInviteUrl` the page uses, so the check is asked about — and
   *  files its verdict under — exactly the string `handleBuy` bills. */
  inviteUrl: string;
  /** «Проверить» was pressed on a field holding no valid link. `GiftGame`
   *  flips the field's "touched" flag from here, so the visible link error it
   *  would otherwise hold back until blur (or the idle pause) shows at once.
   *  A callback rather than state of this hook's own: that flag is the *link
   *  error*'s display timing, shared with the field's `onBlur`, and it
   *  predates this check. */
  onInvalidAttempt: () => void;
}): GiftProfileCheckHandle {
  const [result, setResult] = useState<GiftProfileResult | null>(null);
  const [checking, setChecking] = useState(false);
  // Set when «Проверить» is pressed on a field it cannot run against, so the
  // empty-field case can say what's missing. Only "you haven't pasted the
  // link yet" needs it — a *wrong* link already has its own visible error.
  const [attempted, setAttempted] = useState(false);

  const canonicalInvite = validateInviteUrl(inviteUrl);
  const state = profileCheckState({
    result,
    canonicalInvite,
    inviteHasValue: inviteUrl.trim() !== "",
    attempted,
  });
  // The canonical link the field holds *now*, readable from an async
  // continuation — `canonicalInvite` itself is a render snapshot taken before
  // the await, so a check that resolves after the buyer retyped would compare
  // against the link they had when they pressed the button. Synced from an
  // effect (after commit) rather than assigned during render.
  const currentInviteRef = useRef<string | null>(canonicalInvite);
  useEffect(() => {
    currentInviteRef.current = canonicalInvite;
  }, [canonicalInvite]);
  // The double-submit guard for «Проверить». A ref, not `checking`: the
  // button stays focusable and pressable while a check is in flight (a real
  // `disabled` drops focus to <body> for up to the full 8 s timeout, and only
  // the `found` path ever re-homes it), so the handler is what has to refuse
  // the second press. Set synchronously, before the first `await`, so two
  // taps landing in one tick issue one request.
  const checkInFlightRef = useRef(false);

  async function check(): Promise<void> {
    if (checkInFlightRef.current) return;
    // The canonical form is what the server is asked about, what the verdict
    // is filed under, and the same string `handleBuy` puts in
    // `fulfillment_data.invite_url` — so the check answers for exactly the
    // link that will be bought, and a cosmetic edit to the raw text cannot
    // discard the answer (see `GiftProfileResult.canonicalUrl`).
    const canonical = canonicalInvite;
    if (canonical === null) {
      // A dimmed control that swallows the tap teaches nothing. Pressing it
      // answers either way: a *wrong* link gets the visible link error the
      // field would otherwise hold back until blur or the idle pause, and an
      // *empty* one gets the "paste the link first" note — which the link
      // error cannot produce, since it requires a non-empty value.
      onInvalidAttempt();
      setAttempted(true);
      // No haptic here on purpose: the buzz reports the *check's* answer, and
      // this path never asked anything — same rule `DynamicFields` follows,
      // where haptics fire only on a resolved `PlayerCheckResult`.
      return;
    }
    checkInFlightRef.current = true;
    setChecking(true);
    try {
      const verdict = await checkGiftProfile(canonical);
      setResult({ canonicalUrl: canonical, check: verdict });
      // Only for a verdict that will actually render. If the buyer retyped
      // while this was in flight, `profileCheckState` discards the answer —
      // buzzing success for something nobody sees is worse than silence.
      if (currentInviteRef.current === canonical) {
        // A resolved recipient is the strongest "we see who this is going to"
        // signal in the flow and a rejection is the cheapest moment to catch a
        // typo; the non-blocking verdicts are neither, so they get the neutral
        // tick rather than an error buzz for a fault that was never the
        // buyer's.
        haptic(
          verdict.status === "found" ? "ok" : verdict.status === "not_found" ? "error" : "select",
        );
      }
    } catch {
      // `checkGiftProfile` never rejects (see its doc comment). This is here
      // so the page stays correct on its own if that ever changes — with it,
      // `check` itself cannot reject either, which is what makes the bare
      // `void check()` at the call site safe.
      setResult({ canonicalUrl: canonical, check: { status: "unavailable" } });
    } finally {
      checkInFlightRef.current = false;
      setChecking(false);
    }
  }

  function reopen(): void {
    setResult(null);
    // Belt-and-braces: the load-bearing reset is `onUrlChange`, which every
    // route from "pressed «Проверить» on an empty field" to a collapsed card
    // runs through, so the flag is already false by the time this can be
    // called. Kept so it cannot outlive its meaning if another way of setting
    // it is ever added.
    setAttempted(false);
  }

  function onUrlChange(): void {
    // `attempted` means "«Проверить» was pressed with nothing to check", and
    // any edit — including selecting all and deleting — makes that stale.
    // Leaving it set meant the hint came back every later time the field went
    // empty, with no press behind it: spoken into the middle of the buyer's
    // own retyping, since the note lives in a polite live region.
    setAttempted(false);
  }

  return { state, checking, check, reopen, onUrlChange };
}
