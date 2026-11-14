"use client";

import { Loader2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, use, useState } from "react";

import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { ApiError } from "@/lib/client";
import { headingStyles } from "@/lib/heading";
import { inputStyles } from "@/lib/input";
import { pathFor } from "@/lib/seo";
import { useLoginModal } from "@/store/useLoginModal";

/**
 * Landing page for the link in the verify-email message
 * (`{web_base}/{locale}/auth/verify?token=...`).
 *
 * The link sets the password (2026-11-14 security audit). It used to verify
 * on open and arm whatever password the account held — and an unverified
 * address can be re-registered by anyone, replacing that password with theirs
 * before the owner clicks. The holder of the link now types the password, so
 * only the mailbox owner's can open the account.
 *
 * `POST /auth/verify-email` opens a session — it goes through
 * `useAuth().verifyEmail` so the token is stored and the post-auth funnel runs
 * (seed `/auth/me`, claim this browser's guest orders). Then the account
 * orders list, where the claimed orders show up.
 */
function VerifyInner({ locale }: { locale: string }) {
  const token = useSearchParams().get("token");
  const { verifyEmail } = useAuth();
  const router = useRouter();
  const t = useTranslations("web.auth");
  const tReset = useTranslations("web.passwordReset");
  const tNav = useTranslations("web.nav");
  const openLogin = useLoginModal((st) => st.open);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<"form" | "invalid" | "error">(token ? "form" : "invalid");

  async function submit(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!token) return;
    setBusy(true);
    try {
      await verifyEmail(token, password);
      router.replace(pathFor(locale, "/account/orders"));
    } catch (err) {
      setStatus(err instanceof ApiError && err.status === 401 ? "invalid" : "error");
      setBusy(false);
    }
  }

  if (status === "invalid") {
    return (
      <main className="mx-auto max-w-[420px] px-4 pb-16 pt-[120px] text-center">
        <h1 className={headingStyles("page", "mb-4")}>{t("verifyRequiredTitle")}</h1>
        <p className="text-danger text-[15px] leading-relaxed">{t("verifyInvalid")}</p>
        {/* The copy says to ask for a new link from the sign-in form. */}
        <button
          type="button"
          onClick={openLogin}
          className={`${buttonStyles({ size: "lg" })} mt-6 w-full`}
        >
          {tNav("login")}
        </button>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-[420px] px-4 pb-16 pt-[120px]">
      <h1 className={headingStyles("page", "mb-3")}>{t("verifyTitle")}</h1>
      <p className="text-tx-mute mb-6 text-[15px] leading-relaxed">{t("verifyIntro")}</p>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <label className="block">
          <span className="text-tx-mute mb-1.5 block text-[13px] font-semibold">
            {tReset("newLabel")}
          </span>
          <input
            type="password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
            }}
            minLength={8}
            required
            autoComplete="new-password"
            className={inputStyles()}
          />
        </label>
        {status === "error" && <p className="text-danger text-[13px]">{tReset("error")}</p>}
        <button type="submit" disabled={busy} className={buttonStyles({ size: "lg" })}>
          {busy ? <Loader2 size={18} className="animate-spin" /> : t("verifySubmit")}
        </button>
      </form>
    </main>
  );
}

function VerifyFallback() {
  return (
    <main className="mx-auto flex max-w-[420px] flex-col items-center px-4 pb-16 pt-[120px]">
      <Loader2 size={28} className="animate-spin" />
    </main>
  );
}

export default function VerifyPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = use(params);
  return (
    <Suspense fallback={<VerifyFallback />}>
      <VerifyInner locale={locale} />
    </Suspense>
  );
}
