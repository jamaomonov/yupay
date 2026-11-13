"use client";

import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { buttonStyles } from "@/lib/button";
import { apiFetch } from "@/lib/client";
import { headingStyles } from "@/lib/heading";
import { inputStyles } from "@/lib/input";
import { useLoginModal } from "@/store/useLoginModal";

/** Strings live in `web.passwordReset` (hard-coded Russian on uz/en until 2026-11-13). */
export default function ForgotPage() {
  const t = useTranslations("web.passwordReset");
  const openLogin = useLoginModal((s) => s.open);
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);

  async function handleSubmit(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await apiFetch("/auth/password/forgot", {
        method: "POST",
        anonymous: true,
        body: { email },
      });
    } catch {
      // intentionally swallowed — non-enumerating
    } finally {
      setSubmitting(false);
      setSent(true);
    }
  }

  return (
    <main className="mx-auto max-w-[420px] px-4 pb-16 pt-[120px]">
      <h1 className={headingStyles("page", "mb-3")}>{t("forgotTitle")}</h1>

      {sent ? (
        <p className="text-[15px] leading-relaxed">{t("sent")}</p>
      ) : (
        <>
          <p className="text-tx-mute mb-6 text-[15px] leading-relaxed">{t("forgotIntro")}</p>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <label className="block">
              <span className="text-tx-mute mb-1.5 block text-[13px] font-semibold">
                {t("emailLabel")}
              </span>
              <input
                type="email"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                }}
                required
                className={inputStyles()}
              />
            </label>

            <button type="submit" disabled={submitting} className={buttonStyles({ size: "lg" })}>
              {submitting ? <Loader2 size={18} className="animate-spin" /> : t("send")}
            </button>
          </form>
        </>
      )}
      <button
        type="button"
        onClick={openLogin}
        className="text-tx-mute hover:text-foreground mt-6 text-[14px] font-semibold transition"
      >
        ← {t("backToLogin")}
      </button>
    </main>
  );
}
