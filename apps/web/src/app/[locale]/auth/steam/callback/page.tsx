"use client";

import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "@/lib/auth";
import { pathFor } from "@/lib/seo";
import { toast } from "@/store/useToast";

/**
 * Where Steam sends the customer back. The `openid.*` query params are the
 * whole assertion — this page hands them to `POST /auth/steam` (which
 * re-verifies them with Steam) and walks home with a session.
 *
 * Client-only on purpose: the params must not touch our server logs on the
 * way through (they are a one-time credential), and the session lands in the
 * same storage every other login lands in.
 */
export default function SteamCallbackPage() {
  const { loginWithSteam } = useAuth();
  const router = useRouter();
  const locale = useLocale();
  const t = useTranslations("web.auth");
  const [failed, setFailed] = useState(false);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return; // StrictMode double-mount must not double-POST
    ran.current = true;
    const params: Record<string, string> = {};
    for (const [key, value] of new URLSearchParams(window.location.search)) {
      if (key.startsWith("openid.")) params[key] = value;
    }
    if (Object.keys(params).length === 0) {
      setFailed(true);
      return;
    }
    void loginWithSteam(params)
      .then(() => {
        toast.success(t("signedIn"));
        router.replace(pathFor(locale));
      })
      .catch(() => {
        setFailed(true);
      });
  }, [loginWithSteam, router, locale, t]);

  return (
    <main className="flex min-h-screen items-center justify-center px-6 pt-[120px]">
      <p className="text-tx-mute text-sm">{failed ? t("signInFailed") : t("steamFinishing")}</p>
    </main>
  );
}
