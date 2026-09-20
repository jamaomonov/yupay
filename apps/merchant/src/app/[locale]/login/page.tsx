"use client";

import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { AuthLink, AuthShell } from "@/components/AuthShell";
import { Field, FormError, SubmitButton } from "@/components/Field";
import { ApiError, api, storeTokens, type Tokens } from "@/lib/api";
import { pathFor } from "@/lib/locale-href";

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
      // Three answers, not one. A suspended account now gets its own 403 and
      // its own sentence: folding it into "wrong email or password" sent a
      // real operator round the password-reset loop twice without ever
      // learning the account was frozen. The other failures stay identical on
      // purpose — registration is open, so distinguishing "no such address"
      // from "wrong password" would tell a prober about somebody else's
      // mailbox.
      const status = err instanceof ApiError ? err.status : 0;
      setError(
        status === 429
          ? t("tooManyAttempts")
          : status === 403
            ? t("accountSuspended")
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
