"use client";

import { Loader2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, use, useEffect, useRef, useState } from "react";

import { useAuth } from "@/lib/auth";
import { pathFor } from "@/lib/seo";

/**
 * Landing page for the link in the verify-email message
 * (`{web_base}/{locale}/auth/verify?token=...`, built by
 * `apps/api/.../auth/service.py`'s `register_user`/`resend_verification`).
 *
 * `POST /auth/verify-email` opens a session (`TokensOut`) — this must go
 * through `useAuth().verifyEmail`, not a raw `apiFetch`, so the access token
 * is actually stored and the shared post-auth funnel runs (seed `/auth/me`,
 * claim this browser's guest orders, clear their localStorage copies). Once
 * that settles we hand off to the account orders list, where the claimed
 * order(s) become visible.
 */
function VerifyInner({ locale }: { locale: string }) {
  const token = useSearchParams().get("token");
  const { verifyEmail } = useAuth();
  const router = useRouter();
  const t = useTranslations("web.auth");
  const [status, setStatus] = useState<"pending" | "invalid">(token ? "pending" : "invalid");
  // Effects can re-run (StrictMode, fast refresh); the token is single-use.
  const startedRef = useRef(false);

  useEffect(() => {
    if (!token || startedRef.current) return;
    startedRef.current = true;
    let cancelled = false;
    verifyEmail(token)
      .then(() => {
        if (!cancelled) router.replace(pathFor(locale, "/account/orders"));
      })
      .catch(() => {
        if (!cancelled) setStatus("invalid");
      });
    return () => {
      cancelled = true;
    };
  }, [token, verifyEmail, router, locale]);

  if (status === "invalid") {
    return (
      <main className="mx-auto max-w-[420px] px-4 pb-16 pt-[120px] text-center">
        <h1 className="font-display mb-4 text-2xl font-bold tracking-[-0.02em]">
          {t("verifyRequiredTitle")}
        </h1>
        <p className="text-[15px] leading-relaxed text-[#FF6B6B]">{t("verifyInvalid")}</p>
      </main>
    );
  }

  return (
    <main className="mx-auto flex max-w-[420px] flex-col items-center px-4 pb-16 pt-[120px]">
      <Loader2 size={28} className="animate-spin" />
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
