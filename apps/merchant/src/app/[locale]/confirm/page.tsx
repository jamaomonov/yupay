"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, useState } from "react";

import { AuthLink, AuthShell } from "@/components/AuthShell";
import { Field, FormError, SubmitButton } from "@/components/Field";
import { ApiError, api, storeTokens, type Tokens } from "@/lib/api";
import { pathFor } from "@/lib/locale-href";

const MIN_PASSWORD = 10;

/**
 * The confirmation link sets the password (2026-11-14 security audit).
 *
 * It used to confirm on open and arm whatever password the account held —
 * and anyone can re-register an unconfirmed address, replacing that password
 * with theirs between the owner's registration and their click. The person
 * holding the link now types the password here, so only the mailbox owner's
 * password can ever be the one that opens the cabinet.
 */
function ConfirmForm() {
  const t = useTranslations("merchant.auth");
  const { locale } = useParams<{ locale: string }>();
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const tokens = await api<Tokens>("/confirm", {
        method: "POST",
        anonymous: true,
        body: { token, password },
      });
      storeTokens(tokens);
      router.replace(pathFor(locale, "/cabinet"));
    } catch (cause) {
      // 401: the link is spent or expired — retyping cannot fix that.
      if (cause instanceof ApiError && cause.status === 401) setFailed(true);
      else setError(t("tooManyAttempts"));
      setBusy(false);
    }
  }

  if (token === "" || failed) {
    return (
      <AuthShell
        title={t("confirmFailedTitle")}
        subtitle={t("confirmFailedBody")}
        footer={<AuthLink href={pathFor(locale, "/forgot")} label={t("resendLink")} />}
      />
    );
  }

  return (
    <AuthShell
      title={t("confirmTitle")}
      subtitle={t("confirmSubtitle")}
      footer={<AuthLink href={pathFor(locale, "/login")} label={t("backToLogin")} />}
    >
      <form onSubmit={submit}>
        <FormError message={error} />
        <Field
          label={t("password")}
          type="password"
          value={password}
          onChange={setPassword}
          hint={t("passwordHint")}
          autoComplete="new-password"
          minLength={MIN_PASSWORD}
        />
        <SubmitButton label={t("confirmSubmit")} busy={busy} />
      </form>
    </AuthShell>
  );
}

export default function ConfirmPage() {
  // `useSearchParams` needs a Suspense boundary to keep the route static.
  return (
    <Suspense fallback={null}>
      <ConfirmForm />
    </Suspense>
  );
}
