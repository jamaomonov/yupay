"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useSession } from "@/lib/auth";

export default function LoginPage() {
  const t = useTranslations("partners.login");
  const router = useRouter();
  const { status, signIn } = useSession();
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  // Already signed in — nothing to do here.
  useEffect(() => {
    if (status === "in") router.replace("/panel");
  }, [status, router]);

  async function submit(event: React.SyntheticEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (busy) return;
    const form = new FormData(event.currentTarget);
    const email = form.get("email");
    const password = form.get("password");
    if (typeof email !== "string" || typeof password !== "string") return;

    setBusy(true);
    setFailed(false);
    try {
      await signIn(email, password);
      router.replace("/panel");
    } catch {
      // One message for every failure — wrong password, unknown address,
      // suspended account. The API deliberately does not distinguish them, and
      // a friendlier UI here would undo that: "no such account" turns this
      // form into a way to find out who is a partner.
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  const field =
    "border-border bg-card-2 rounded-btn h-12 w-full border px-4 text-[15px] outline-none focus:border-primary/60";

  return (
    <main className="grid-cell flex min-h-dvh items-center justify-center px-5 py-16">
      <div className="border-border bg-card w-full max-w-sm rounded-2xl border p-7">
        <h1 className="font-display text-xl font-bold">{t("title")}</h1>

        <form onSubmit={(e) => void submit(e)} className="mt-6 space-y-4">
          <label className="block">
            <span className="text-tx-mute mb-2 block text-[13px]">{t("email")}</span>
            <input name="email" type="email" required autoComplete="email" className={field} />
          </label>
          <label className="block">
            <span className="text-tx-mute mb-2 block text-[13px]">{t("password")}</span>
            <input
              name="password"
              type="password"
              required
              autoComplete="current-password"
              className={field}
            />
          </label>

          {failed && <p className="text-[13px] text-red-400">{t("failed")}</p>}

          <button
            type="submit"
            disabled={busy}
            className="bg-primary text-primary-foreground rounded-btn h-12 w-full text-[15px] font-semibold transition hover:brightness-110 disabled:opacity-50"
          >
            {busy ? t("submitting") : t("submit")}
          </button>
        </form>

        <p className="text-tx-mute mt-6 text-center text-[13px]">
          {t("noAccount")}{" "}
          <Link href="/#apply" className="text-primary underline">
            {t("applyLink")}
          </Link>
        </p>
      </div>
    </main>
  );
}
