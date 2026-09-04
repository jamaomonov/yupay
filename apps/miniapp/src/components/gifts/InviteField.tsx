import { Check, Loader2 } from "lucide-react";
import { useEffect, useId, useRef } from "react";

import type { ProfileCheckState } from "@/lib/gift-profile";

import { SafeImage } from "@/components/ui/safe-image";
import { useT } from "@/lib/i18n";

/**
 * The recipient's Steam link: the field, the «Проверить» button beside it,
 * and every state the pre-purchase profile check can be in.
 *
 * A gift goes to whoever the link resolves to and there is no undo once
 * G-Engine's bot sends the friend invite, so a `found` verdict collapses the
 * field into a card showing the avatar and nickname the gift is actually
 * headed for — the last thing the buyer sees before paying is a face and a
 * name, not a URL they stopped reading three taps ago.
 *
 * **Only a definitive `not_found` blocks the purchase** (`profileCheckBlocks`
 * in `lib/gift-profile.ts`). `unsupported` (an `s.team` friend-invite token
 * the Steam Web API cannot resolve at all) and `unavailable` (no API key, a
 * Steam outage, a timeout, our own 5xx) render as a neutral note beside a Buy
 * button that stays live: a check that fails on our side must never cost a
 * sale.
 *
 * Split out of `GiftBuyPanel` rather than added to it purely to keep both
 * files inside the repo's 300-LOC soft limit for TS — no behaviour of the
 * payment section moved. All state is the caller's (`GiftGame`), which needs
 * the verdict for `canBuy`/`payHint`/the confirm dialog anyway.
 */
export function InviteField({
  inviteUrl,
  inviteValid,
  onInviteUrlChange,
  onInviteBlur,
  showInviteError,
  onOpenGuide,
  profile,
  checking,
  onCheck,
  onReopen,
}: {
  inviteUrl: string;
  /** Whether the text currently in the field parses as a Steam link at all
   *  (`validateInviteUrl`) — dims «Проверить», but never swallows its tap;
   *  see the button below. */
  inviteValid: boolean;
  onInviteUrlChange: (value: string) => void;
  /** Flips the field's "touched" flag — one of the two triggers (alongside a
   *  short idle pause) that lets `showInviteError` actually render, instead
   *  of firing on the very first keystroke. See
   *  `GiftGame.tsx::showInviteInvalid`. */
  onInviteBlur: () => void;
  showInviteError: boolean;
  onOpenGuide: () => void;
  /** The whole render decision for the check — `GiftGame`'s
   *  `profileCheckState(...)`. */
  profile: ProfileCheckState;
  /** A check request is in flight. */
  checking: boolean;
  onCheck: () => void;
  /** Reopen the collapsed field from the card's «Изменить». */
  onReopen: () => void;
}) {
  const { t } = useT();
  // The single required field in the whole checkout, and previously the one
  // with NO label association at all — a `<label>` with no `htmlFor` next to
  // an `<input>` with no `id` (2026-09-04 accessibility audit): a screen
  // reader announced only "text field".
  const inviteId = useId();
  const inviteErrorId = `${inviteId}-error`;
  const profileErrorId = `${inviteId}-profile-error`;
  const profileNoteId = `${inviteId}-profile`;

  const found = profile.found;
  const inputRef = useRef<HTMLInputElement>(null);
  const editRef = useRef<HTMLButtonElement>(null);
  // Focus follows the collapse in both directions. «Проверить» unmounts along
  // with the field it sits next to, dropping focus to <body> — a keyboard or
  // switch-control user's next move would restart at the top of the screen
  // with no signal that anything happened. Hand it to the card's «Изменить»,
  // and hand it back to the field when «Изменить» unmounts it in turn. Done
  // from one effect on the transition rather than inside the two handlers
  // because the `found` verdict lands asynchronously, in the *caller's*
  // promise, not in a tap handler this component can hook.
  const wasFound = useRef(false);
  useEffect(() => {
    const isFound = found !== null;
    if (isFound !== wasFound.current) {
      wasFound.current = isFound;
      // After paint: the node being focused is the one this very render is
      // mounting, so it does not exist yet at effect time on some engines.
      const target = isFound ? editRef : inputRef;
      requestAnimationFrame(() => target.current?.focus());
    }
  }, [found]);

  // What the always-mounted live region actually holds. A `found` verdict has
  // no *visible* note — the card says it — but it still has to be said out
  // loud: the sighted buyer gets an avatar and a name, while a screen-reader
  // user would otherwise get focus moved to a button whose entire accessible
  // name is «Изменить». That is the one moment this whole feature exists for.
  const announce = found
    ? t("gifts.game.profileFound", { nickname: found.nickname })
    : profile.noteKey
      ? t(profile.noteKey)
      : "";
  const describedBy =
    [
      showInviteError ? inviteErrorId : null,
      profile.alertKey !== null ? profileErrorId : null,
      profile.noteKey !== null ? profileNoteId : null,
    ]
      .filter((id): id is string => id !== null)
      .join(" ") || undefined;

  return (
    <div className="space-y-2">
      {/* No `<input>` to point at once the field has collapsed. */}
      {found ? (
        <p className="text-[11px] font-semibold uppercase tracking-wide text-white/50">
          {t("gifts.game.inviteLabel")}
        </p>
      ) : (
        <label
          htmlFor={inviteId}
          className="text-[11px] font-semibold uppercase tracking-wide text-white/50"
        >
          {t("gifts.game.inviteLabel")}
        </label>
      )}

      {found ? (
        <div className="flex items-center gap-2.5 rounded-2xl border border-emerald-500/40 bg-emerald-500/[0.06] py-1.5 pl-1.5 pr-3">
          {found.avatarUrl !== null ? (
            <SafeImage
              src={found.avatarUrl}
              // Decorative: the nickname it belongs to is right beside it, and
              // an avatar has nothing of its own to announce.
              alt=""
              className="h-11 w-11 shrink-0 rounded-full object-cover"
              // `SafeImage` already covers the third-party host failing — this
              // is the same green tick the top-up check pill uses.
              fallback={
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400">
                  <Check size={18} strokeWidth={3} />
                </span>
              }
            />
          ) : (
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400">
              <Check size={18} strokeWidth={3} />
            </span>
          )}
          <div className="min-w-0 flex-1 leading-tight">
            <div className="truncate text-[14px] font-bold text-white">{found.nickname}</div>
            {/* The link it resolved to, kept visible: the field it replaced is
              gone, and the buyer should still be able to see what they
              pasted. */}
            <div className="truncate text-[12px] text-white/45">{inviteUrl.trim()}</div>
          </div>
          <button
            type="button"
            ref={editRef}
            onClick={onReopen}
            // The only way back out of a confirmed-but-wrong recipient, so it
            // gets a real tap target rather than a bare 13px word.
            className="inline-flex min-h-[44px] shrink-0 items-center px-1 text-[13px] font-medium text-white/45 active:opacity-70"
          >
            {t("field.checkEdit")}
          </button>
        </div>
      ) : (
        <div className="flex items-stretch gap-2">
          <input
            id={inviteId}
            ref={inputRef}
            type="text"
            value={inviteUrl}
            onChange={(e) => {
              onInviteUrlChange(e.target.value);
            }}
            onBlur={onInviteBlur}
            placeholder={t("gifts.game.invitePlaceholder")}
            aria-invalid={showInviteError || profile.blocks}
            aria-describedby={describedBy}
            className="h-11 min-w-0 flex-1 rounded-xl border bg-transparent px-3 text-sm text-white outline-none"
            style={{ borderColor: "hsl(var(--border))" }}
          />
          <button
            type="button"
            // `aria-disabled`, not `disabled`: a real `disabled` button drops
            // the tap, leaving no moment at which to explain why nothing
            // happened. The caller's `onCheck` answers either way — a *wrong*
            // link gets the field error it would otherwise hold back until
            // blur, an *empty* one gets the note below. Same posture as the
            // web panel and `CheckablePlayerField`.
            aria-disabled={!inviteValid}
            disabled={checking}
            onClick={onCheck}
            className={`inline-flex shrink-0 items-center justify-center gap-2 rounded-xl px-5 text-[13px] font-semibold transition-opacity active:opacity-70 disabled:opacity-40 ${
              inviteValid ? "" : "opacity-40"
            }`}
            style={{
              background: "hsl(var(--primary) / 0.12)",
              border: "1px solid hsl(var(--primary) / 0.35)",
              color: "hsl(var(--primary))",
            }}
          >
            {checking && <Loader2 size={15} className="animate-spin" />}
            {checking ? t("field.checking") : t("field.check")}
          </button>
        </div>
      )}

      {showInviteError && (
        <p id={inviteErrorId} className="text-[13px] text-red-400">
          {t("gifts.game.inviteError")}
        </p>
      )}
      {profile.alertKey !== null && (
        /* The only verdict that blocks Buy, and the only one that reads as an
          error. `role="alert"` announces on insertion, which is what this
          state needs. */
        <p id={profileErrorId} role="alert" className="text-[13px] text-red-400">
          {t(profile.alertKey)}
        </p>
      )}
      {/* Always mounted, empty when there is nothing to say: a live region
        *inserted* into the page rather than updated in place is commonly
        missed, which would leave the non-blocking verdicts announced to
        nobody. `sr-only` while there is no visible note, so the parent's
        `space-y-2` reserves no gap for an empty node and the `found` case
        announces without printing a second copy of the card. */}
      <div
        id={profileNoteId}
        role="status"
        aria-live="polite"
        className={profile.noteKey !== null ? "text-[13px] text-white/50" : "sr-only"}
      >
        {announce}
      </div>

      {/* Tells the buyer what to put *in the field*, so it goes away once the
        field has collapsed into a confirmed recipient — otherwise the most
        confident moment in the flow ends with instructions to fill in
        something that is no longer on screen. */}
      {found === null && (
        <button
          type="button"
          onClick={onOpenGuide}
          className="text-primary text-[13px] font-semibold"
        >
          {t("gifts.game.inviteGuideCta")}
        </button>
      )}
    </div>
  );
}
