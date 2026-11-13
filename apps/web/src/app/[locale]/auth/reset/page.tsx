"use client";

import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { Suspense, useState } from "react";

import { buttonStyles } from "@/lib/button";
import { ApiError, apiFetch } from "@/lib/client";
import { pathFor } from "@/lib/seo";
import { useLoginModal } from "@/store/useLoginModal";

/** Strings live in `web.passwordReset` (hard-coded Russian on uz/en until 2026-11-13). */
function ResetInner() {
  const t = useTranslations("web.passwordReset");
  const locale = useLocale();
  const token = useSearchParams().get("token");
  const openLogin = useLoginModal((s) => s.open);
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState<"idle" | "ok" | "invalid" | "error">(
    token ? "idle" : "invalid",
  );

  async function handleSubmit(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!token) return;
    setSubmitting(true);
    try {
      await apiFetch("/auth/password/reset", {
        method: "POST",
        anonymous: true,
        body: { token, new_password: password },
      });
      setStatus("ok");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setStatus("invalid");
      } else {
        setStatus("error");
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (status === "ok") {
    return (
      <main className="mx-auto max-w-[420px] px-4 pb-16 pt-[120px]">
        <h1 className="font-display mb-6 text-2xl font-bold tracking-[-0.02em]">
          {t("doneTitle")}
        </h1>
        <p className="text-[15px] leading-relaxed">
          {t("done")}{" "}
          <button type="button" onClick={openLogin} className="text-primary hover:underline">
            {t("signIn")}
          </button>
        </p>
      </main>
    );
  }

  if (status === "invalid") {
    return (
      <main className="mx-auto max-w-[420px] px-4 pb-16 pt-[120px]">
        <h1 className="font-display mb-3 text-2xl font-bold tracking-[-0.02em]">
          {t("forgotTitle")}
        </h1>
        <p className="text-danger text-[15px] leading-relaxed">{t("invalid")}</p>
        {/* Not a dead end: the next step is a fresh link. */}
        <Link
          href={pathFor(locale, "/auth/forgot")}
          className={`${buttonStyles({ size: "lg" })} mt-6 w-full`}
        >
          {t("requestNew")}
        </Link>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-[420px] px-4 pb-16 pt-[120px]">
      <h1 className="font-display mb-6 text-2xl font-bold tracking-[-0.02em]">{t("newTitle")}</h1>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <label className="block">
          <span className="text-tx-mute mb-1.5 block text-[13px] font-semibold">
            {t("newLabel")}
          </span>
          <input
            type="password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
            }}
            minLength={8}
            required
            className="border-border-2 bg-card focus:border-primary rounded-btn h-[46px] w-full border px-3.5 text-[15px] outline-none transition"
          />
        </label>

        {status === "error" && <p className="text-danger text-[13px]">{t("error")}</p>}

        <button type="submit" disabled={submitting} className={buttonStyles({ size: "lg" })}>
          {submitting ? <Loader2 size={18} className="animate-spin" /> : t("save")}
        </button>
      </form>
    </main>
  );
}

function ResetFallback() {
  const t = useTranslations("web.passwordReset");
  return (
    <main className="mx-auto max-w-[420px] px-4 pb-16 pt-[120px]">
      <h1 className="font-display mb-6 text-2xl font-bold tracking-[-0.02em]">{t("newTitle")}</h1>
    </main>
  );
}

export default function ResetPage() {
  return (
    <Suspense fallback={<ResetFallback />}>
      <ResetInner />
    </Suspense>
  );
}
