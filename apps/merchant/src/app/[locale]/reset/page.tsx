"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, useState } from "react";

import { AuthLink, AuthShell } from "@/components/AuthShell";
import { Field, FormError, SubmitButton } from "@/components/Field";
import { pathFor } from "@/lib/locale-href";
import { ApiError, api, storeTokens, type Tokens } from "@/lib/api";

const MIN_PASSWORD = 10;

function ResetForm() {
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
      const tokens = await api<Tokens>("/password/reset", {
        method: "POST",
        anonymous: true,
        body: { token, password },
      });
      // Signing straight in is the API's own answer, and it is safe for the
      // reason the confirm link is: holding it proves the mailbox.
      storeTokens(tokens);
      router.replace(pathFor(locale, "/cabinet"));
    } catch (cause) {
      // A 401 means the link is spent or expired — a different screen, since
      // no amount of retyping a password fixes it.
      if (cause instanceof ApiError && cause.status === 401) setFailed(true);
      else setError(t("tooManyAttempts"));
      setBusy(false);
    }
  }

  if (token === "" || failed) {
    return (
      <AuthShell
        title={t("resetFailedTitle")}
        subtitle={t("resetFailedBody")}
        footer={<AuthLink href={pathFor(locale, "/forgot")} label={t("forgotTitle")} />}
      />
    );
  }

  return (
    <AuthShell
      title={t("resetTitle")}
      subtitle={t("resetSubtitle")}
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
        <SubmitButton label={t("submitReset")} busy={busy} />
      </form>
    </AuthShell>
  );
}

export default function ResetPage() {
  // `useSearchParams` opts a route into client rendering, and Next requires
  // the boundary to be explicit — the same shape `/confirm` uses.
  return (
    <Suspense fallback={null}>
      <ResetForm />
    </Suspense>
  );
}
