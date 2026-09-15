"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, useEffect, useRef, useState } from "react";

import { AuthLink, AuthShell } from "@/components/AuthShell";
import { pathFor } from "@/lib/locale-href";
import { api, storeTokens, type Tokens } from "@/lib/api";

function Confirming() {
  const t = useTranslations("merchant.auth");
  const { locale } = useParams<{ locale: string }>();
  const router = useRouter();
  const token = useSearchParams().get("token");
  const [failed, setFailed] = useState(false);
  // React 18+ runs effects twice in development. The link is single-use, so a
  // second call would consume it and report a failure for a confirmation that
  // actually worked.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    if (!token) {
      setFailed(true);
      return;
    }
    void (async () => {
      try {
        const tokens = await api<Tokens>("/confirm", {
          method: "POST",
          anonymous: true,
          body: { token },
        });
        storeTokens(tokens);
        router.replace(pathFor(locale, "/cabinet"));
      } catch {
        setFailed(true);
      }
    })();
  }, [token, locale, router]);

  if (failed) {
    return (
      <AuthShell
        title={t("confirmFailedTitle")}
        subtitle={t("confirmFailedBody")}
        // Was "register again", which is wrong the moment a resend exists:
        // the second registration answers `email_taken` and the person is
        // stuck where they started.
        footer={<AuthLink href={pathFor(locale, "/forgot")} label={t("resendLink")} />}
      />
    );
  }
  return <AuthShell title={t("confirming")} />;
}

export default function ConfirmPage() {
  // `useSearchParams` needs a Suspense boundary to keep the route static.
  return (
    <Suspense fallback={null}>
      <Confirming />
    </Suspense>
  );
}
