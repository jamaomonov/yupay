"use client";

import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { AuthLink, AuthShell } from "@/components/AuthShell";
import { Field, FormError, SubmitButton } from "@/components/Field";
import { GoogleButton } from "@/components/GoogleButton";
import { ApiError, api, storeTokens, type Tokens } from "@/lib/api";
import { pathFor } from "@/lib/locale-href";

export default function RegisterPage() {
  const t = useTranslations("merchant.auth");
  const { locale } = useParams<{ locale: string }>();
  const router = useRouter();
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

  // Google proves the address, so there is no mail to wait for: straight in.
  // The offer box still has to be ticked — Google cannot accept it for them.
  async function google(accessToken: string) {
    setBusy(true);
    setError(null);
    try {
      const tokens = await api<Tokens>("/google", {
        method: "POST",
        anonymous: true,
        body: {
          access_token: accessToken,
          accept_offer: true,
          title: title.trim() === "" ? null : title.trim(),
        },
      });
      storeTokens(tokens);
      router.replace(pathFor(locale, "/cabinet"));
    } catch (err) {
      const e = err instanceof ApiError ? err : null;
      setError(
        e?.status === 403
          ? t("accountSuspended")
          : e?.status === 429
            ? t("tooManyAttempts")
            : t("googleFailed"),
      );
      setBusy(false);
    }
  }

  function offerTicked(): boolean {
    if (accepted) return true;
    setError(t("offerRequired"));
    return false;
  }

  if (sent) {
    // No token, no session, no redirect into the cabinet: the address is not
    // proven until the link is opened, and registration is open to anyone.
    //
    // With a footer, because without one this screen was the end of the
    // funnel: a confirmation mail that lands in spam — or never arrives,
    // since a failed send deliberately leaves the account standing rather
    // than rolling the registration back — left the reader on a page with no
    // links at all. `/forgot` is where the resend lives, the same place
    // `/confirm` sends a reader with an expired link.
    return (
      <AuthShell
        title={t("checkMailTitle")}
        subtitle={t("checkMailBody", { email })}
        footer={<AuthLink href={pathFor(locale, "/forgot")} label={t("resendLink")} />}
      />
    );
  }

  return (
    <AuthShell
      title={t("registerTitle")}
      subtitle={t("registerSubtitle")}
      footer={
        <>
          {t("haveAccount")} <AuthLink href={pathFor(locale, "/login")} label={t("submitLogin")} />
        </>
      }
    >
      <FormError message={error} />
      {/* Above the Google button: it registers on the spot, and the offer
          has to be accepted on both paths. */}
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
          {t("acceptOffer")} <AuthLink href={pathFor(locale, "/offer")} label={t("offerLink")} />
        </span>
      </label>
      <GoogleButton
        onToken={(token) => void google(token)}
        beforeOpen={offerTicked}
        disabled={busy}
      />
      <form onSubmit={submit} noValidate={false}>
        {/* «Магазин или канал», not «компания»: the FAQ promises no company is
            needed, and a Telegram admin stalled on the old label. The API
            still wants 2–128 characters, so the browser enforces the same. */}
        <Field
          label={t("company")}
          value={title}
          onChange={setTitle}
          hint={t("companyHint")}
          autoComplete="organization"
          minLength={2}
          maxLength={128}
        />
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
        <SubmitButton label={t("submitRegister")} busy={busy} />
      </form>
    </AuthShell>
  );
}
