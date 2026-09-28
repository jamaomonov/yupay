import { Check, Loader2 } from "lucide-react";
import { useEffect, useId, useState } from "react";

import type { TradeLinkLine } from "@/lib/skin-buy";

import { useT } from "@/lib/i18n";
import { tradeLinkShapeOk, tradeLinkVerdict } from "@/lib/skin-buy";
import { checkTradeLink, getTradeLink } from "@/lib/skins";
import { openExternalLink } from "@/lib/telegram";

/** Steam's own page with the «Trade URL» box. */
const WHERE_TO_FIND = "https://steamcommunity.com/my/tradeoffers/privacy#trade_offer_access_url";
const CHECK_DEBOUNCE_MS = 400;

type Shown = TradeLinkLine | "checking" | null;

/**
 * Where the skin goes: the customer's Steam trade link, prefilled from their
 * last skin order and checked as it is pasted (private inventory, trade ban,
 * a Steam hold). A failed check blocks paying; an unavailable one does not.
 * Mirrors the web's `SkinTradeLinkField`.
 */
export function SkinTradeLinkInput({
  onChange,
}: {
  onChange: (state: { url: string; usable: boolean }) => void;
}) {
  const { t } = useT();
  const id = useId();
  const [url, setUrl] = useState("");
  const [shown, setShown] = useState<Shown>(null);

  useEffect(() => {
    let live = true;
    getTradeLink()
      .then((saved) => {
        if (live && saved) setUrl((typed) => typed || saved);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    const value = url.trim();
    if (value === "" || !tradeLinkShapeOk(value)) {
      setShown(value === "" ? null : "invalid");
      onChange({ url: value, usable: false });
      return;
    }
    let live = true;
    setShown("checking");
    onChange({ url: value, usable: false });
    const timer = setTimeout(() => {
      void checkTradeLink(value)
        .then((v) => tradeLinkVerdict(v))
        .catch(() => tradeLinkVerdict(null))
        .then((v) => {
          if (!live) return;
          setShown(v.line);
          onChange({ url: value, usable: v.usable });
        });
    }, CHECK_DEBOUNCE_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
    // `onChange` is the parent's setter; re-running on its identity would re-check.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  const bad = shown !== null && shown !== "ok" && shown !== "checking";
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <label
          htmlFor={id}
          className="text-[11px] font-semibold uppercase tracking-wide text-white/50"
        >
          {t("cs2.buy.tradeLink")}
        </label>
        <button
          type="button"
          onClick={() => {
            openExternalLink(WHERE_TO_FIND);
          }}
          className="text-primary min-h-[32px] text-[12px] font-semibold"
        >
          {t("cs2.buy.whereToFind")}
        </button>
      </div>
      <input
        id={id}
        type="url"
        inputMode="url"
        autoComplete="off"
        spellCheck={false}
        value={url}
        placeholder={t("cs2.buy.tradeLinkPlaceholder")}
        onChange={(e) => {
          setUrl(e.target.value);
        }}
        aria-invalid={bad ? true : undefined}
        aria-describedby={`${id}-verdict`}
        className="h-11 w-full rounded-xl border bg-transparent px-3 text-[13px] text-white outline-none"
        style={{ borderColor: bad ? "#FF6B6B" : "hsl(var(--border))" }}
      />
      <p id={`${id}-verdict`} className="min-h-[18px] text-[12px]" aria-live="polite">
        {shown === "checking" && (
          <span className="inline-flex items-center gap-1 text-white/50">
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
            {t("cs2.buy.checking")}
          </span>
        )}
        {shown === "ok" && (
          <span className="inline-flex items-center gap-1 text-emerald-400">
            <Check className="h-3 w-3" aria-hidden="true" />
            {t("cs2.buy.verdict.ok")}
          </span>
        )}
        {bad && <span className="text-[#FF6B6B]">{t(`cs2.buy.verdict.${shown}`)}</span>}
      </p>
    </div>
  );
}
