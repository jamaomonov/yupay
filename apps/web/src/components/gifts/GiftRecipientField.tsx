"use client";

import { Check, ExternalLink, Loader2 } from "lucide-react";
import Image from "next/image";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";

import { InviteGuide } from "./InviteGuide";

import type { GiftProfileCheck } from "@/lib/gifts";

import { canonicalInviteUrl, inviteProfileHref, type RecipientVerdict } from "@/lib/gift-invite";
import { checkGiftProfile, profileCheckBlocks } from "@/lib/gifts";
import { isOptimizable } from "@/lib/image";

/** How long the invite field waits, idle, before showing an error on its
 *  own — mirrors the catalog search debounces elsewhere in this module.
 *  Blurring the field shows the error immediately regardless. */
const INVITE_ERROR_DEBOUNCE_MS = 600;

/** The invite field's caption styling, shared by the `<label>` that owns the
 *  input and the plain caption that stands in for it once the field collapses
 *  into the confirmed-recipient card (a `<label>` whose `htmlFor` points at a
 *  control that is no longer rendered announces as a dangling label). */
const FIELD_LABEL_CLASS = "text-tx-dim text-[11px] font-semibold uppercase tracking-[0.08em]";

/**
 * Who the gift is going to: the invite-link field, the advisory «Проверить»
 * lookup beside it, and the confirmed-recipient card the pair collapses into.
 *
 * Everything about *asking* — the debounced link error, the in-flight guard,
 * the focus choreography, the live region — is owned here. Two things flow
 * out to `GiftPurchasePanel`: the link itself (`onChange`, since the panel is
 * what sends it to the API and names it in the confirm dialog) and the check's
 * verdict (`onCheckResult`), which is the one thing about the recipient that
 * Buy reasons about. Mirrors `CheckablePlayerField` in `PurchasePanel`, with
 * one deliberate difference — see `check` below.
 */
export function GiftRecipientField({
  value,
  onChange,
  check,
  onCheckResult,
}: {
  /** The invite link exactly as the buyer typed it. */
  value: string;
  onChange: (value: string) => void;
  /** The verdict that currently applies to `value`, or `null` when none does
   *  (`currentVerdict`). Handed down rather than derived here — and reported
   *  back up through `onCheckResult` rather than mirrored with an effect the
   *  way `CheckablePlayerField` does it — because it gates Buy: an effect
   *  lands a commit later, which would leave the button payable for one
   *  render after this field had already painted the `not_found` that blocks
   *  it. */
  check: GiftProfileCheck | null;
  /** Reports a fresh verdict, filed under the profile it was asked about, or
   *  `null` when the card's «Изменить» drops it. */
  onCheckResult: (verdict: RecipientVerdict | null) => void;
}) {
  const t = useTranslations("web.gifts.game");
  // The check button and the confirmation card reuse `PurchasePanel`'s
  // existing copy (`check`/`checking`/`checkEdit`) rather than forking a
  // second translation of the same three words into this namespace.
  const ts = useTranslations("web.store");

  // The profile the field currently points at, or `null` when it points at
  // nothing yet — the recipient check's own key, and the accept/reject gate.
  const canonicalInvite = canonicalInviteUrl(value);
  const inviteValid = canonicalInvite !== null;
  const inviteHasValue = value.trim() !== "";
  // Whether the current text *would* show an error, ignoring timing — the
  // gate the buy button and `payHint` reason off, unconditionally.
  const inviteWrong = inviteHasValue && !inviteValid;
  // Timing only, for the visible error paragraph below the field: it used to
  // fire on the very first keystroke, well before the buyer had finished
  // pasting or typing (2026-09-04 review). Shown once the field is blurred,
  // or after a short idle pause — whichever comes first — never live on
  // every change.
  const [inviteTouched, setInviteTouched] = useState(false);
  const [inviteIdle, setInviteIdle] = useState(false);
  useEffect(() => {
    setInviteIdle(false);
    if (!inviteWrong) return;
    const timer = setTimeout(() => {
      setInviteIdle(true);
    }, INVITE_ERROR_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [value, inviteWrong]);
  const inviteInvalid = inviteWrong && (inviteTouched || inviteIdle);
  const inviteHref = inviteProfileHref(value);

  const [profileChecking, setProfileChecking] = useState(false);
  // Set when «Проверить» is pressed on a field it cannot run against, so the
  // empty-field case can say what's missing. Only "you haven't pasted the
  // link yet" needs it — a *wrong* link already has its own visible error;
  // announcing the empty one before the buyer has tried would be noise.
  // Mirrors `CheckablePlayerField`'s `attempted`.
  const [checkAttempted, setCheckAttempted] = useState(false);
  const inviteRef = useRef<HTMLInputElement>(null);
  const editRef = useRef<HTMLButtonElement>(null);
  // The double-submit guard for «Проверить». A ref, not `profileChecking`:
  // the button stays focusable and pressable while a check is in flight (a
  // real `disabled` drops focus to <body> for up to the full 8 s timeout, and
  // only the `found` path ever re-homes it), so the handler is what has to
  // refuse the second press (2026-09-04 review round 1).
  const checkInFlightRef = useRef(false);
  const profileFound = check?.status === "found" ? check : null;
  // The one verdict that blocks the purchase. `profileCheckBlocks` is `true`
  // for exactly one of them — Steam's own "no such profile" — so an
  // unsupported link type, a Steam outage, and a link nobody checked all
  // leave the buyer free to pay: a check that fails on our side must never
  // cost a sale.
  const profileBlocks = profileCheckBlocks(check);

  async function runProfileCheck(): Promise<void> {
    if (checkInFlightRef.current) return;
    // The canonical form is what the server is asked about and what the
    // verdict is filed under — one profile, one answer, however the buyer
    // happened to type it.
    const url = canonicalInvite;
    if (url === null) {
      // A dimmed control that swallows the click teaches nothing. Pressing it
      // answers either way: a *wrong* link gets the visible link error the
      // field would otherwise hold back until blur or the idle pause, and an
      // *empty* one gets the "paste the link first" note (`profileNote`
      // below) — which `inviteWrong` alone cannot produce, since it requires
      // the field to be non-empty.
      setInviteTouched(true);
      setCheckAttempted(true);
      return;
    }
    checkInFlightRef.current = true;
    setProfileChecking(true);
    try {
      const result = await checkGiftProfile(url);
      onCheckResult({ canonicalUrl: url, check: result });
      if (result.status === "found") {
        // The «Проверить» button unmounts along with the field it sits next
        // to, dropping focus to <body> — a keyboard user's next Tab would
        // restart at the top of the page with no signal that anything
        // happened. Hand focus to the card's «Изменить», the mirror of what
        // `reopenInvite` does on the way back.
        requestAnimationFrame(() => editRef.current?.focus());
      }
    } catch {
      // `checkGiftProfile` never rejects (see its doc comment). This is here
      // so the component stays correct on its own if that ever changes —
      // with it, `runProfileCheck` itself cannot reject either, which is what
      // makes the bare `void runProfileCheck()` at the call site safe.
      onCheckResult({ canonicalUrl: url, check: { status: "unavailable" } });
    } finally {
      checkInFlightRef.current = false;
      setProfileChecking(false);
    }
  }

  /** Reopen the collapsed field from the card's «Изменить» control. */
  function reopenInvite(): void {
    onCheckResult(null);
    // Belt-and-braces. The load-bearing reset is the input's own `onChange`
    // (see there): every route from "pressed «Проверить» on an empty field"
    // to a collapsed card runs through it, so the flag is already false by
    // the time this can be called. Kept so the flag cannot outlive its
    // meaning if another way of setting it is ever added.
    setCheckAttempted(false);
    requestAnimationFrame(() => inviteRef.current?.focus());
  }

  const inviteId = useId();
  const inviteErrorId = `${inviteId}-error`;
  const profileErrorId = `${inviteId}-profile-error`;
  const profileNoteId = `${inviteId}-profile`;

  // The one blocking verdict, kept apart from the notes below: it renders as
  // a `role="alert"`, which screen readers do announce on insertion.
  const profileAlert: string | null = profileBlocks ? t("profileNotFound") : null;
  // Everything else the check has to say about the link currently in the
  // field. `found` says it in the card instead, so it has no note. This text
  // lives in a live region that is always mounted (see the render), because
  // NVDA and JAWS commonly miss a `role="status"` node that is *inserted*
  // rather than updated in place — which would have made `unsupported` and
  // `unavailable` silent.
  const profileNote: string | null =
    checkAttempted && !inviteHasValue
      ? // «Проверить» pressed on an empty field: `inviteWrong` cannot speak
        // for this case (it requires a non-empty value), so without this the
        // button is a silent no-op. Reuses the Buy button's own wording for
        // the same missing thing rather than forking a fourth sentence.
        t("payHintInvite")
      : check === null || check.status === "found" || profileBlocks
        ? null
        : check.status === "unsupported"
          ? t("profileUnsupported")
          : t("profileUnavailable");
  // What the live region actually holds. A `found` verdict has no *visible*
  // note — the card says it — but it still has to be said out loud: the
  // sighted buyer gets an avatar and a name, while a screen-reader user
  // previously got focus moved to a button whose entire accessible name is
  // «Изменить». That is the one moment this whole feature exists for, so it
  // is announced — and only announced: the region goes `sr-only` whenever
  // `profileNote` is null, so this never renders as a second, redundant copy
  // of the card.
  const profileAnnounce: string =
    profileFound !== null
      ? t("profileFound", { nickname: profileFound.nickname })
      : (profileNote ?? "");
  // The shape error and the check verdict describe the same input, so they
  // are announced together rather than the later one hiding the earlier.
  const inviteDescribedBy =
    [
      inviteInvalid ? inviteErrorId : null,
      profileAlert !== null ? profileErrorId : null,
      profileNote !== null ? profileNoteId : null,
    ]
      .filter((id): id is string => id !== null)
      .join(" ") || undefined;

  return (
    <div className="space-y-2">
      {profileFound !== null ? (
        <p className={FIELD_LABEL_CLASS}>{t("inviteLabel")}</p>
      ) : (
        <label htmlFor={inviteId} className={FIELD_LABEL_CLASS}>
          {t("inviteLabel")}
        </label>
      )}
      {profileFound !== null ? (
        /* Confirmed recipient — the field collapses into who the link
          actually points to, so the last thing the buyer sees before
          paying is a face and a name rather than a URL they have already
          stopped reading. Mirrors `CheckablePlayerField`'s confirmation
          pill in `PurchasePanel`, plus the avatar gifts have and it
          doesn't. */
        <div className="rounded-btn flex items-center gap-2.5 border border-emerald-500/40 bg-emerald-500/[0.06] py-1.5 pl-1.5 pr-4">
          {profileFound.avatarUrl !== null ? (
            <Image
              data-testid="gift-profile-avatar"
              src={profileFound.avatarUrl}
              // Decorative: the nickname it belongs to is right beside it,
              // and an avatar has nothing of its own to announce.
              alt=""
              width={48}
              height={48}
              // `avatars.steamstatic.com` is a third-party host — see
              // `lib/image.ts`: the optimizer 504s rather than degrading
              // when such a host is slow, which would lose the whole card.
              unoptimized={!isOptimizable(profileFound.avatarUrl)}
              className="h-12 w-12 shrink-0 rounded-full object-cover"
            />
          ) : (
            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400">
              <Check size={20} strokeWidth={3} aria-hidden="true" />
            </span>
          )}
          <div className="min-w-0 flex-1 leading-tight">
            <div className="truncate text-[14px] font-bold">{profileFound.nickname}</div>
            {/* The link it resolved to, kept visible: the field it
              replaced is gone, and the buyer should still be able to see
              what they pasted. */}
            <div className="text-tx-dim truncate text-[12px]">{value.trim()}</div>
          </div>
          <button
            type="button"
            ref={editRef}
            onClick={reopenInvite}
            // The recipient's name is part of what focusing this control
            // reads out, not only what the live region announced a moment
            // earlier (2026-09-04 final review). The announcement and this
            // focus move land in the same commit, and screen readers
            // commonly drop a pending polite message when focus moves —
            // which, in the found state, left the user with "Изменить,
            // кнопка" and nothing about who the gift was going to, since
            // the input that used to reference the region has unmounted.
            aria-describedby={profileNoteId}
            // `min-h-[44px]` matching the «Открыть профиль» anchor below:
            // this is the only way back out of a confirmed-but-wrong
            // recipient, and on mobile it was a 13px word with no padding.
            className="text-tx-dim hover:text-tx-mute inline-flex min-h-[44px] shrink-0 items-center px-1 text-[13px] font-medium transition"
          >
            {ts("checkEdit")}
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="min-w-0 flex-1">
            <input
              id={inviteId}
              ref={inviteRef}
              type="text"
              value={value}
              onChange={(e) => {
                onChange(e.target.value);
                // The flag means "«Проверить» was pressed with nothing to
                // check", and any edit — including selecting all and
                // deleting — makes that stale. Leaving it set meant the
                // hint came back every later time the field went empty,
                // with no press behind it: on a polite live region, spoken
                // into the middle of the buyer's own retyping. Clearing
                // here also covers "reset after a successful check", since
                // a check can only run once an edit made the field
                // non-empty.
                setCheckAttempted(false);
              }}
              onBlur={() => {
                setInviteTouched(true);
              }}
              placeholder={t("invitePlaceholder")}
              aria-invalid={inviteInvalid || profileBlocks ? true : undefined}
              aria-describedby={inviteDescribedBy}
              className="border-border bg-bg rounded-btn h-11 w-full border px-3 text-sm"
            />
          </div>
          <button
            type="button"
            // `aria-disabled`, not `disabled`: a real `disabled` button
            // drops the click, leaving no moment at which to explain why
            // nothing happened. `runProfileCheck` answers with the link
            // error instead. Same posture as `CheckablePlayerField`.
            aria-disabled={!inviteValid}
            // Busy, never `disabled`, while a check runs (2026-09-04
            // review round 1): disabling drops focus to <body> the
            // instant a keyboard user activates the button, and only the
            // `found` path ever re-homes it — on `not_found`/
            // `unavailable` they would be left nowhere for up to the full
            // 8 s timeout. `runProfileCheck`'s own in-flight guard
            // refuses the second press.
            aria-busy={profileChecking ? true : undefined}
            onClick={() => {
              void runProfileCheck();
            }}
            // Neutral, not primary: the check is advisory — everything
            // except a definitive "no such profile" lets the buyer carry
            // on — and in lime it would compete with the real CTA.
            className={`border-border-2 text-tx-mute hover:border-tx-dim hover:text-foreground hover:bg-muted rounded-btn inline-flex h-11 shrink-0 items-center justify-center gap-2 border px-5 text-[14px] font-semibold transition ${
              inviteValid ? "" : "opacity-40"
            }`}
          >
            {profileChecking && <Loader2 size={16} className="animate-spin" aria-hidden="true" />}
            {profileChecking ? ts("checking") : ts("check")}
          </button>
        </div>
      )}
      {inviteInvalid && (
        <p id={inviteErrorId} className="text-[13px] text-[#FF6B6B]">
          {t("inviteError")}
        </p>
      )}
      {profileAlert !== null && (
        /* The only verdict that blocks Buy, and the only one that reads
          as an error. `role="alert"` announces on insertion, which is
          what this state needs. */
        <p id={profileErrorId} role="alert" className="text-[13px] text-[#FF6B6B]">
          {profileAlert}
        </p>
      )}
      {/* Always mounted, empty when there is nothing to say: NVDA and JAWS
        commonly miss a live region that is *inserted* into the page rather
        than updated in place, which would leave the non-blocking verdicts
        («нельзя проверить», «Steam не отвечает») announced to nobody.
        `sr-only` while empty rather than a plain empty block, so the
        parent's `space-y-2` doesn't reserve a gap for a node with nothing
        in it — it stays in the accessibility tree either way, which is
        the whole point of keeping it mounted. */}
      <div
        id={profileNoteId}
        data-testid="gift-profile-live"
        role="status"
        aria-live="polite"
        className={profileNote !== null ? "text-tx-dim text-[13px]" : "sr-only"}
      >
        {profileAnnounce}
      </div>
      {/* The free half of the deferred server-side profile checker
        (Task 6a): the buyer opens the pasted link themselves, in a new
        tab, and verifies it's the right person before paying
        (2026-09-04 review). */}
      {inviteHref && (
        <a
          href={inviteHref}
          target="_blank"
          rel="noreferrer noopener"
          className="text-primary inline-flex min-h-[44px] items-center gap-1 text-[13px] font-semibold hover:underline"
        >
          {t("openProfileLink")}
          <ExternalLink size={14} aria-hidden="true" />
        </a>
      )}
      {/* "Ссылка на профиль Steam получателя" reads, to a buyer purchasing
        for themselves, as though they're in the wrong place — this
        covers that case inline rather than leaving it unsaid
        (2026-09-04 review). Both this and the guide below tell the buyer
        what to put *in the field*, so both go away once the field has
        collapsed into a confirmed recipient — otherwise the most
        confident moment in the flow ends with instructions to fill in
        something that is no longer on screen. */}
      {profileFound === null && (
        <p className="text-tx-dim text-[12px] leading-snug">{t("inviteSelfNote")}</p>
      )}
      {/* The two sentences that explain the entire model used to sit
        *below* the Buy button, in 12px dim text — past the decision.
        Moved here, next to the field where the recipient first becomes
        a concept (2026-09-04 review). */}
      <div className="text-tx-dim space-y-1 text-[12px] leading-relaxed">
        <p>{t("timeline")}</p>
        <p>{t("accept")}</p>
      </div>
      {profileFound === null && <InviteGuide />}
    </div>
  );
}
