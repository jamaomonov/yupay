"use client";

import { Loader2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { buttonStyles } from "@/lib/button";
import { ApiError, apiFetch } from "@/lib/client";
import { useLoginModal } from "@/store/useLoginModal";

function ResetInner() {
  const token = useSearchParams().get("token");
  const openLogin = useLoginModal((s) => s.open);
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState<"idle" | "ok" | "invalid" | "error">(
    token ? "idle" : "invalid",
  );

  async function handleSubmit(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!token) return;
    setSubmitting(true);
    try {
      await apiFetch("/auth/password/reset", {
        method: "POST",
        anonymous: true,
        body: { token, new_password: password },
      });
      setStatus("ok");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setStatus("invalid");
      } else {
        setStatus("error");
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (status === "ok") {
    return (
      <main className="mx-auto max-w-[420px] px-4 py-16">
        <h1 className="font-display mb-6 text-2xl font-bold tracking-[-0.02em]">Пароль изменён</h1>
        <p className="text-[15px] leading-relaxed">
          Ваш пароль успешно изменён.{" "}
          <button type="button" onClick={openLogin} className="text-primary hover:underline">
            Войти
          </button>
        </p>
      </main>
    );
  }

  if (status === "invalid") {
    return (
      <main className="mx-auto max-w-[420px] px-4 py-16">
        <h1 className="font-display mb-6 text-2xl font-bold tracking-[-0.02em]">Сброс пароля</h1>
        <p className="text-[15px] leading-relaxed text-[#FF6B6B]">
          Ссылка недействительна или устарела.
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-[420px] px-4 py-16">
      <h1 className="font-display mb-6 text-2xl font-bold tracking-[-0.02em]">Новый пароль</h1>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <label className="block">
          <span className="text-tx-mute mb-1.5 block text-[13px] font-semibold">Новый пароль</span>
          <input
            type="password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
            }}
            minLength={8}
            required
            className="border-border bg-card focus:border-primary h-[46px] w-full rounded-[12px] border px-3.5 text-[15px] outline-none transition"
          />
        </label>

        {status === "error" && (
          <p className="text-[13px] text-[#FF6B6B]">Что-то пошло не так. Попробуйте ещё раз.</p>
        )}

        <button type="submit" disabled={submitting} className={buttonStyles({ size: "lg" })}>
          {submitting ? <Loader2 size={18} className="animate-spin" /> : "Сохранить пароль"}
        </button>
      </form>
    </main>
  );
}

function ResetFallback() {
  return (
    <main className="mx-auto max-w-[420px] px-4 py-16">
      <h1 className="font-display mb-6 text-2xl font-bold tracking-[-0.02em]">Новый пароль</h1>
    </main>
  );
}

export default function ResetPage() {
  return (
    <Suspense fallback={<ResetFallback />}>
      <ResetInner />
    </Suspense>
  );
}
