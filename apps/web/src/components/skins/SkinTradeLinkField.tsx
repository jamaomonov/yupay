"use client";

import { Check, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useState } from "react";

import type { TradeLinkReason } from "@/lib/skins";

import { checkTradeLink, getTradeLink } from "@/lib/skins";

/** Steam's own page with the «Trade URL» box. */
const WHERE_TO_FIND = "https://steamcommunity.com/my/tradeoffers/privacy#trade_offer_access_url";
const LINK_SHAPE =
  /^https:\/\/steamcommunity\.com\/tradeoffer\/new\/\?partner=\d{1,12}&token=[\w-]{6,16}$/;
const CHECK_DEBOUNCE_MS = 400;

type Verdict = TradeLinkReason | "ok" | "checking" | null;

/**
 * Where the skin goes: the customer's Steam trade link, prefilled from their
 * last purchase and checked as it is typed or pasted (private inventory, trade
 * ban, a Steam hold). A failed check blocks paying; an unavailable one does not.
 */
export function SkinTradeLinkField({
  signedIn,
  onChange,
}: {
  signedIn: boolean;
  onChange: (state: { url: string; usable: boolean }) => void;
}) {
  const t = useTranslations("web.skins.buy");
  const id = useId();
  const [url, setUrl] = useState("");
  const [verdict, setVerdict] = useState<Verdict>(null);

  useEffect(() => {
    if (!signedIn) return;
    let live = true;
    getTradeLink()
      .then((saved) => {
        // Never over what the customer pasted before the saved link arrived.
        if (live && saved) setUrl((typed) => typed || saved);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [signedIn]);

  useEffect(() => {
    const value = url.trim();
    if (value === "") {
      setVerdict(null);
      onChange({ url: value, usable: false });
      return;
    }
    if (!LINK_SHAPE.test(value)) {
      setVerdict("invalid");
      onChange({ url: value, usable: false });
      return;
    }
    let live = true;
    setVerdict("checking");
    onChange({ url: value, usable: false });
    const timer = setTimeout(() => {
      checkTradeLink(value)
        .then((v) => {
          if (!live) return;
          setVerdict(v.ok ? (v.reason === "unavailable" ? null : "ok") : v.reason);
          onChange({ url: value, usable: v.ok });
        })
        .catch(() => {
          if (!live) return;
          setVerdict(null); // the check is advisory: an outage never blocks
          onChange({ url: value, usable: true });
        });
    }, CHECK_DEBOUNCE_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
    // `onChange` is the parent's setter; re-running on its identity would re-check.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  const bad = verdict !== null && verdict !== "ok" && verdict !== "checking";
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={id} className="text-[13px] font-semibold">
          {t("tradeLink")}
        </label>
        <a
          href={WHERE_TO_FIND}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary text-[12px] font-semibold hover:underline"
        >
          {t("whereToFind")}
        </a>
      </div>
      <input
        id={id}
        type="url"
        inputMode="url"
        autoComplete="off"
        spellCheck={false}
        value={url}
        placeholder={t("tradeLinkPlaceholder")}
        onChange={(e) => setUrl(e.target.value)}
        aria-invalid={bad}
        aria-describedby={`${id}-verdict`}
        className={`bg-bg rounded-btn h-11 w-full border px-3 text-[13px] ${
          bad ? "border-[#FF6B6B]" : "border-border"
        }`}
      />
      <p id={`${id}-verdict`} className="min-h-[18px] text-[12px]" aria-live="polite">
        {verdict === "checking" && (
          <span className="text-tx-dim inline-flex items-center gap-1">
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
            {t("checking")}
          </span>
        )}
        {verdict === "ok" && (
          <span className="inline-flex items-center gap-1 text-emerald-400">
            <Check className="h-3 w-3" aria-hidden />
            {t("verdict.ok")}
          </span>
        )}
        {bad && <span className="text-[#FF6B6B]">{t(`verdict.${verdict}`)}</span>}
      </p>
    </div>
  );
}
