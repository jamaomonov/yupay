"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { useProfile } from "@/lib/panel";

/** The storefront a partner sends their audience to. */
const STOREFRONT = process.env.NEXT_PUBLIC_STOREFRONT_URL ?? "https://yupay.uz";

export default function CodesPage() {
  const t = useTranslations("partners.panel");
  const profile = useProfile();
  const [copied, setCopied] = useState<string | null>(null);

  async function copy(value: string, marker: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(marker);
      setTimeout(() => {
        setCopied(null);
      }, 1600);
    } catch {
      // Clipboard permission refused, or an insecure origin. The code is on
      // screen and selectable either way, so this is not worth an error.
    }
  }

  const codes = profile.data?.codes ?? [];

  if (profile.isSuccess && codes.length === 0) {
    return <p className="text-tx-mute text-[14px] leading-relaxed">{t("codesEmpty")}</p>;
  }

  const button =
    "border-border-2 rounded-btn hover:bg-card-2 h-10 shrink-0 border px-3.5 text-[13px] font-semibold transition";

  return (
    <div className="space-y-4">
      {codes.map((code) => {
        const link = `${STOREFRONT}/?ref=${encodeURIComponent(code.code)}`;
        return (
          <div key={code.id} className="border-border bg-card rounded-xl border p-6">
            <p className="font-display text-primary text-2xl font-bold tracking-wider">
              {code.code}
            </p>

            <dl className="mt-4 grid grid-cols-2 gap-4">
              <div>
                <dt className="text-tx-mute text-[13px]">{t("codeDiscount")}</dt>
                <dd className="mt-1 font-mono text-[15px]">{code.discount_percent}%</dd>
              </div>
              <div>
                <dt className="text-tx-mute text-[13px]">{t("codeCommission")}</dt>
                <dd className="mt-1 font-mono text-[15px]">{code.commission_percent}%</dd>
              </div>
            </dl>

            <div className="mt-5 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void copy(code.code, `c-${code.id}`)}
                className={button}
              >
                {copied === `c-${code.id}` ? t("copied") : t("codeCopy")}
              </button>
              <button
                type="button"
                onClick={() => void copy(link, `l-${code.id}`)}
                className={button}
              >
                {copied === `l-${code.id}` ? t("copied") : t("codeCopyLink")}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
