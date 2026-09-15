"use client";

import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { AuthLink, AuthShell } from "@/components/AuthShell";
import { Field, SubmitButton } from "@/components/Field";
import { api } from "@/lib/api";

/**
 * Ask for a reset link, or for the confirmation mail again.
 *
 * One screen for both, because from the outside they are one situation — "I
 * cannot get in and I do not know why" — and the API answers both the same:
 * `204`, whatever the address was. A person who registered but never
 * confirmed does not know that is their problem; sending both links means
 * they do not have to.
 */
export default function ForgotPage() {
  const t = useTranslations("merchant.auth");
  const { locale } = useParams<{ locale: string }>();
  const [email, setEmail] = useState("");
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    // Both, and neither result is read: the endpoints answer 204 for an
    // address that exists and for one that does not, and a screen that
    // behaved differently would put back the enumeration oracle they were
    // written to close. A network failure lands on the same screen, which is
    // the honest outcome — the next attempt is the same click.
    await Promise.allSettled([
      api("/password/forgot", { method: "POST", anonymous: true, body: { email } }),
      api("/confirm/resend", { method: "POST", anonymous: true, body: { email } }),
    ]);
    setSentTo(email);
    setBusy(false);
  }

  if (sentTo !== null) {
    return (
      <AuthShell
        title={t("forgotSentTitle")}
        subtitle={t("forgotSentBody", { email: sentTo })}
        footer={<AuthLink href={`/${locale}/login`} label={t("backToLogin")} />}
      />
    );
  }

  return (
    <AuthShell
      title={t("forgotTitle")}
      subtitle={t("forgotSubtitle")}
      footer={<AuthLink href={`/${locale}/login`} label={t("backToLogin")} />}
    >
      <form onSubmit={submit}>
        <Field
          label={t("email")}
          type="email"
          value={email}
          onChange={setEmail}
          autoComplete="email"
        />
        <SubmitButton label={t("submitForgot")} busy={busy} />
      </form>
    </AuthShell>
  );
}
