"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { Wordmark } from "@/components/Wordmark";
import { Link } from "@/i18n/navigation";
import { SHELL } from "@/components/landing/shell";
import { useSession } from "@/lib/auth";

export default function LoginPage() {
  const t = useTranslations("partners.login");
  const brand = useTranslations("partners.nav")("brand");
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
    "border-border bg-card h-12 w-full rounded-full border px-5 text-[15px] outline-none transition focus:border-primary/60";

  return (
    // No card. The landing has none either, and a form floating in a box was
    // the one screen still speaking the old language.
    <main className="flex min-h-dvh flex-col">
      <div className="border-border border-b">
        <div className={`${SHELL} flex items-center justify-between gap-4 py-5`}>
          <Link href="/" className="flex items-center gap-3.5">
            <Wordmark height={22} />
            <span className="border-border text-tx-mute hidden border-l pl-3.5 font-mono text-[11px] uppercase tracking-[0.14em] sm:inline sm:text-[12px]">
              {brand}
            </span>
          </Link>
          <LocaleSwitcher />
        </div>
      </div>

      <div className={`${SHELL} flex flex-1 items-center py-16`}>
        <div className="w-full max-w-sm">
          <h1 className="font-display text-[clamp(1.9rem,5vw,2.6rem)] font-extrabold leading-[1.04] tracking-[-0.035em]">
            {t("title")}
          </h1>

          <form onSubmit={(e) => void submit(e)} className="mt-8 space-y-4">
            <label className="block">
              <span className="text-tx-mute mb-2 block font-mono text-[11px] uppercase tracking-[0.12em]">
                {t("email")}
              </span>
              <input name="email" type="email" required autoComplete="email" className={field} />
            </label>
            <label className="block">
              <span className="text-tx-mute mb-2 block font-mono text-[11px] uppercase tracking-[0.12em]">
                {t("password")}
              </span>
              <input
                name="password"
                type="password"
                required
                autoComplete="current-password"
                className={field}
              />
            </label>

            {failed && (
              <p role="alert" className="text-[13px] text-red-400">
                {t("failed")}
              </p>
            )}

            <button
              type="submit"
              disabled={busy}
              className="bg-primary text-primary-foreground h-12 w-full rounded-full text-[15px] font-bold transition hover:brightness-110 disabled:opacity-50"
            >
              {busy ? t("submitting") : t("submit")}
            </button>
          </form>

          <p className="text-tx-mute mt-7 text-[13px]">
            {t("noAccount")}{" "}
            <Link href="/#apply" className="text-primary underline">
              {t("applyLink")}
            </Link>
          </p>
        </div>
      </div>
    </main>
  );
}
