"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import type { Profile } from "@/lib/types";

import { api } from "@/lib/api";
import { formatUsd, toCents } from "@/lib/money";

export default function Dashboard() {
  const t = useTranslations("merchant.cabinet");
  const { locale } = useParams<{ locale: string }>();
  const [profile, setProfile] = useState<Profile | null>(null);

  useEffect(() => {
    void api<Profile>("/me")
      .then(setProfile)
      .catch(() => {
        // The shell's own session check has already redirected anyone without
        // one; a failure here is a revoked session mid-view, and the next
        // navigation resolves it. Nothing to say on this screen.
      });
  }, []);

  const balance = profile ? toCents(profile.balance_usd) : null;

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">{profile?.title ?? " "}</h1>

      <section className="border-border bg-card mt-6 rounded-xl border p-6">
        <p className="text-tx-mute text-sm">{t("balance")}</p>
        <p className="mt-1 font-mono text-3xl font-semibold">
          {balance === null ? "—" : `$${formatUsd(balance)}`}
        </p>

        {balance === 0n && (
          // The one thing a fresh account needs to be told, and the spec's
          // whole onboarding shape: the catalog is open, buying waits on
          // support. Said without naming the mechanism — no "deposit through
          // support" process detail on a customer-facing surface.
          <div className="border-border mt-5 border-t pt-5">
            <p className="font-medium">{t("balanceEmptyTitle")}</p>
            <p className="text-tx-mute mt-1.5 text-sm leading-relaxed">{t("balanceEmptyBody")}</p>
            <a
              href="https://t.me/yupay_support"
              className="border-border rounded-btn mt-4 inline-flex px-4 py-2 text-sm font-semibold"
            >
              {t("requestDeposit")}
            </a>
          </div>
        )}
      </section>

      <section className="mt-6 grid gap-4 sm:grid-cols-2">
        <Link
          href={`/${locale}/cabinet/catalog`}
          className="border-border bg-card-2 rounded-xl border p-5 font-semibold"
        >
          {t("navCatalog")}
        </Link>
        <div className="border-border bg-card rounded-xl border p-5">
          <p className="text-tx-mute text-sm">{t("recentOrders")}</p>
          <p className="text-tx-dim mt-2 text-sm">{t("noOrders")}</p>
        </div>
      </section>
    </div>
  );
}
