"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { TelegramLoginButton } from "./TelegramLoginButton";

import { buttonStyles } from "@/lib/button";

const schema = z.object({
  email: z.string().email(),
  password: z.string().min(8),
});
type Values = z.infer<typeof schema>;

export function AuthForm({
  mode,
  locale,
  onSubmit,
}: {
  mode: "login" | "register";
  locale: string;
  onSubmit: (v: Values) => Promise<void>;
}) {
  const t = useTranslations("web.auth");
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) });

  return (
    <form
      onSubmit={handleSubmit(async (v) => {
        setError(null);
        try {
          await onSubmit(v);
        } catch {
          setError(t(mode === "login" ? "loginError" : "registerError"));
        }
      })}
      className="flex flex-col gap-4"
    >
      <label className="block">
        <span className="text-tx-mute mb-1.5 block text-[13px] font-semibold">{t("email")}</span>
        <input
          type="email"
          {...register("email")}
          className="border-border bg-card focus:border-primary h-[46px] w-full rounded-[12px] border px-3.5 text-[15px] outline-none transition"
        />
        {errors.email && (
          <span className="mt-1 block text-xs text-[#FF6B6B]">{t("emailInvalid")}</span>
        )}
      </label>
      <label className="block">
        <span className="text-tx-mute mb-1.5 block text-[13px] font-semibold">{t("password")}</span>
        <input
          type="password"
          {...register("password")}
          className="border-border bg-card focus:border-primary h-[46px] w-full rounded-[12px] border px-3.5 text-[15px] outline-none transition"
        />
        {errors.password && (
          <span className="mt-1 block text-xs text-[#FF6B6B]">{t("passwordShort")}</span>
        )}
      </label>

      <button type="submit" disabled={isSubmitting} className={buttonStyles({ size: "lg" })}>
        {isSubmitting ? <Loader2 size={18} className="animate-spin" /> : t(mode)}
      </button>
      {error && <p className="text-center text-[13px] text-[#FF6B6B]">{error}</p>}

      <div className="text-tx-mute flex justify-between text-[13px]">
        {mode === "login" ? (
          <>
            <Link href={`/${locale}/register`} className="hover:text-tx">
              {t("toRegister")}
            </Link>
            <Link href={`/${locale}/auth/forgot`} className="hover:text-tx">
              {t("forgot")}
            </Link>
          </>
        ) : (
          <Link href={`/${locale}/login`} className="hover:text-tx">
            {t("toLogin")}
          </Link>
        )}
      </div>

      <div className="border-border/70 my-2 border-t" />
      <TelegramLoginButton />
    </form>
  );
}
