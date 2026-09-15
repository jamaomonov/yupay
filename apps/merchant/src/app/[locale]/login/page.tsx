"use client";

import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { AuthLink, AuthShell } from "@/components/AuthShell";
import { Field, FormError, SubmitButton } from "@/components/Field";
import { pathFor } from "@/lib/locale-href";
import { ApiError, api, storeTokens, type Tokens } from "@/lib/api";

export default function LoginPage() {
  const t = useTranslations("merchant.auth");
  const { locale } = useParams<{ locale: string }>();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const tokens = await api<Tokens>("/login", {
        method: "POST",
        anonymous: true,
        body: { email, password },
      });
      storeTokens(tokens);
      router.replace(pathFor(locale, "/cabinet"));
    } catch (err) {
      // One message for every failure, because the API answers the same for
      // every failure — and the copy says what an unconfirmed operator should
      // actually do, since that is the one case they can fix themselves.
      setError(
        err instanceof ApiError && err.status === 429
          ? t("tooManyAttempts")
          : t("invalidCredentials"),
      );
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title={t("loginTitle")}
      footer={
        <div className="space-y-2">
          <p>
            {t("noAccount")}{" "}
            <AuthLink href={pathFor(locale, "/register")} label={t("submitRegister")} />
          </p>
          <p>
            <AuthLink href={pathFor(locale, "/forgot")} label={t("forgotLink")} />
          </p>
        </div>
      }
    >
      <form onSubmit={submit}>
        <FormError message={error} />
        <Field
          label={t("email")}
          type="email"
          value={email}
          onChange={setEmail}
          autoComplete="email"
        />
        <Field
          label={t("password")}
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
        />
        <SubmitButton label={t("submitLogin")} busy={busy} />
      </form>
    </AuthShell>
  );
}
