"use client";

import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { AuthLink, AuthShell } from "@/components/AuthShell";
import { Field, FormError, SubmitButton } from "@/components/Field";
import { ApiError, api } from "@/lib/api";

export default function RegisterPage() {
  const t = useTranslations("merchant.auth");
  const { locale } = useParams<{ locale: string }>();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [title, setTitle] = useState("");
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!accepted) {
      setError(t("offerRequired"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api("/register", {
        method: "POST",
        anonymous: true,
        body: { email, password, title, accept_offer: true },
      });
      setSent(true);
    } catch (err) {
      // The last branch used to claim the address was taken, whatever went
      // wrong — so a network blip, a 500, or a client-side parse error all
      // read as "you already have an account". Only say that when the API
      // says it.
      if (err instanceof ApiError && err.code === "email_taken") setError(t("emailTaken"));
      else if (err instanceof ApiError && err.status === 429) setError(t("tooManyAttempts"));
      else setError(t("registerFailed"));
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    // No token, no session, no redirect into the cabinet: the address is not
    // proven until the link is opened, and registration is open to anyone.
    return <AuthShell title={t("checkMailTitle")} subtitle={t("checkMailBody", { email })} />;
  }

  return (
    <AuthShell
      title={t("registerTitle")}
      subtitle={t("registerSubtitle")}
      footer={
        <>
          {t("haveAccount")} <AuthLink href={`/${locale}/login`} label={t("submitLogin")} />
        </>
      }
    >
      <form onSubmit={submit} noValidate={false}>
        <FormError message={error} />
        <Field label={t("company")} value={title} onChange={setTitle} autoComplete="organization" />
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
          hint={t("passwordHint")}
          autoComplete="new-password"
          minLength={10}
        />
        <label className="text-tx-mute mb-5 flex items-start gap-2.5 text-sm leading-relaxed">
          <input
            type="checkbox"
            checked={accepted}
            onChange={(event) => {
              setAccepted(event.target.checked);
            }}
            className="mt-0.5"
          />
          <span>
            {t("acceptOffer")} <AuthLink href={`/${locale}/offer`} label={t("offerLink")} />
          </span>
        </label>
        <SubmitButton label={t("submitRegister")} busy={busy} />
      </form>
    </AuthShell>
  );
}
