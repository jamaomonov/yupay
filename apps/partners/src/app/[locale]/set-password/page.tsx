"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, useState } from "react";

import { api, ApiError } from "@/lib/api";

type State = "idle" | "sending" | "error-used" | "error-short" | "error-generic";

function SetPasswordForm() {
  const t = useTranslations("partners.setPassword");
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token");
  const [state, setState] = useState<State>("idle");

  if (token === null) {
    return <p className="text-tx-mute text-[14px] leading-relaxed">{t("noToken")}</p>;
  }

  async function submit(event: React.SyntheticEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (state === "sending") return;
    const value = new FormData(event.currentTarget).get("password");
    if (typeof value !== "string") return;
    if (value.length < 8) {
      setState("error-short");
      return;
    }

    setState("sending");
    try {
      await api("/api/v1/affiliate/auth/set-password", {
        method: "POST",
        body: { token, password: value },
        anonymous: true,
      });
      router.replace("/login");
    } catch (err) {
      // A consumed or expired link is the common case and deserves its own
      // sentence — "try again" is useless advice for a link that will never
      // work again.
      setState(err instanceof ApiError && err.status === 401 ? "error-used" : "error-generic");
    }
  }

  const message =
    state === "error-used"
      ? t("errUsed")
      : state === "error-short"
        ? t("errShort")
        : state === "error-generic"
          ? t("errGeneric")
          : null;

  return (
    <form onSubmit={(e) => void submit(e)} className="mt-6 space-y-4">
      <label className="block">
        <span className="text-tx-mute mb-2 block font-mono text-[11px] uppercase tracking-[0.12em]">
          {t("password")}
        </span>
        <input
          name="password"
          type="password"
          required
          minLength={8}
          autoComplete="new-password"
          className="border-border bg-card focus:border-primary/60 h-12 w-full rounded-full border px-5 text-[15px] outline-none transition"
        />
        <span className="text-tx-dim mt-1.5 block text-[12px]">{t("hint")}</span>
      </label>

      {message !== null && <p className="text-[13px] text-red-400">{message}</p>}

      <button
        type="submit"
        disabled={state === "sending"}
        className="bg-primary text-primary-foreground h-12 w-full rounded-full text-[15px] font-bold transition hover:brightness-110 disabled:opacity-50"
      >
        {state === "sending" ? t("submitting") : t("submit")}
      </button>
    </form>
  );
}

export default function SetPasswordPage() {
  const t = useTranslations("partners.setPassword");
  return (
    <main className="flex min-h-dvh items-center px-5 py-16">
      <div className="mx-auto w-full max-w-sm">
        <h1 className="font-display text-[clamp(1.8rem,5vw,2.4rem)] font-extrabold leading-[1.05] tracking-[-0.035em]">
          {t("title")}
        </h1>
        <p className="text-tx-mute mt-3 text-[14px]">{t("subtitle")}</p>
        {/* useSearchParams suspends during prerender; without this boundary the
            whole route opts out of static rendering. */}
        <Suspense fallback={null}>
          <SetPasswordForm />
        </Suspense>
      </div>
    </main>
  );
}
