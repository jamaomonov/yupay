"use client";

import { Loader2 } from "lucide-react";
import { useState } from "react";

import { buttonStyles } from "@/lib/button";
import { apiFetch } from "@/lib/client";

export default function ForgotPage() {
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);

  async function handleSubmit(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await apiFetch("/auth/password/forgot", {
        method: "POST",
        anonymous: true,
        body: { email },
      });
    } catch {
      // intentionally swallowed — non-enumerating
    } finally {
      setSubmitting(false);
      setSent(true);
    }
  }

  return (
    <main className="mx-auto max-w-[420px] px-4 py-16">
      <h1 className="font-display mb-6 text-2xl font-bold tracking-[-0.02em]">Сброс пароля</h1>

      {sent ? (
        <p className="text-[15px] leading-relaxed">
          Если адрес зарегистрирован, мы отправили письмо со ссылкой для сброса пароля.
        </p>
      ) : (
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <label className="block">
            <span className="text-tx-mute mb-1.5 block text-[13px] font-semibold">
              Электронная почта
            </span>
            <input
              type="email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
              }}
              required
              className="border-border bg-card focus:border-primary h-[46px] w-full rounded-[12px] border px-3.5 text-[15px] outline-none transition"
            />
          </label>

          <button type="submit" disabled={submitting} className={buttonStyles({ size: "lg" })}>
            {submitting ? <Loader2 size={18} className="animate-spin" /> : "Отправить ссылку"}
          </button>
        </form>
      )}
    </main>
  );
}
