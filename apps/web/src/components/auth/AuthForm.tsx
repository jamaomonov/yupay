"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { TelegramLoginButton } from "./TelegramLoginButton";

import { buttonStyles } from "@/lib/button";
import { ApiError } from "@/lib/client";
import { pathFor } from "@/lib/seo";

const baseSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8),
  confirmPassword: z.string().optional(),
});
type FormValues = z.infer<typeof baseSchema>;

export function AuthForm({
  mode,
  locale,
  onSubmit,
  showTelegram = true,
  onToggleMode,
}: {
  mode: "login" | "register";
  locale: string;
  onSubmit: (v: FormValues) => Promise<void>;
  showTelegram?: boolean;
  /** Switch between login and register in place (used by the modal). */
  onToggleMode?: () => void;
}) {
  const t = useTranslations("web.auth");
  const [error, setError] = useState<string | null>(null);
  // In register mode the password must be confirmed; the refine is a no-op for
  // login (where the confirm field isn't rendered).
  const schema = useMemo(
    () =>
      baseSchema.refine((d) => mode !== "register" || d.confirmPassword === d.password, {
        message: "mismatch",
        path: ["confirmPassword"],
      }),
    [mode],
  );
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  return (
    <form
      onSubmit={handleSubmit(async (v) => {
        setError(null);
        try {
          await onSubmit(v);
        } catch (err) {
          // A suspended account must not be told "wrong email or password":
          // the customer would conclude they mistyped it and go round the
          // password-reset loop instead of contacting support.
          if (err instanceof ApiError && err.type?.endsWith("/account-suspended")) {
            setError(t("suspendedError"));
            return;
          }
          setError(t(mode === "login" ? "loginError" : "registerError"));
        }
      })}
      className="flex flex-col gap-4"
    >
      <label className="block">
        <span className="text-tx-mute mb-1.5 block text-[13px] font-semibold">{t("email")}</span>
        <input
          type="email"
          id="auth-email"
          aria-invalid={errors.email ? true : undefined}
          aria-describedby={errors.email ? "auth-email-error" : undefined}
          autoComplete="email"
          aria-required="true"
          {...register("email")}
          className="border-border bg-card focus:border-primary rounded-btn h-[46px] w-full border px-3.5 text-[15px] outline-none transition"
        />
        {errors.email && (
          <span id="auth-email-error" className="mt-1 block text-xs text-[#FF6B6B]">
            {t("emailInvalid")}
          </span>
        )}
      </label>
      <label className="block">
        <span className="text-tx-mute mb-1.5 block text-[13px] font-semibold">{t("password")}</span>
        <input
          type="password"
          id="auth-password"
          aria-invalid={errors.password ? true : undefined}
          aria-describedby={errors.password ? "auth-password-error" : undefined}
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          aria-required="true"
          {...register("password")}
          className="border-border bg-card focus:border-primary rounded-btn h-[46px] w-full border px-3.5 text-[15px] outline-none transition"
        />
        {errors.password && (
          <span id="auth-password-error" className="mt-1 block text-xs text-[#FF6B6B]">
            {t("passwordShort")}
          </span>
        )}
      </label>
      {mode === "register" && (
        <label className="block">
          <span className="text-tx-mute mb-1.5 block text-[13px] font-semibold">
            {t("confirmPassword")}
          </span>
          <input
            type="password"
            id="auth-confirm-password"
            aria-invalid={errors.confirmPassword ? true : undefined}
            aria-describedby={errors.confirmPassword ? "auth-confirm-password-error" : undefined}
            autoComplete="new-password"
            aria-required="true"
            {...register("confirmPassword")}
            className="border-border bg-card focus:border-primary rounded-btn h-[46px] w-full border px-3.5 text-[15px] outline-none transition"
          />
          {errors.confirmPassword && (
            <span id="auth-confirm-password-error" className="mt-1 block text-xs text-[#FF6B6B]">
              {t("passwordMismatch")}
            </span>
          )}
        </label>
      )}

      <button type="submit" disabled={isSubmitting} className={buttonStyles({ size: "lg" })}>
        {isSubmitting ? <Loader2 size={18} className="animate-spin" /> : t(mode)}
      </button>
      {error && (
        <p role="alert" className="text-center text-[13px] text-[#FF6B6B]">
          {error}
        </p>
      )}

      <div className="text-tx-mute flex justify-between text-[13px]">
        {mode === "login" ? (
          <>
            {onToggleMode ? (
              <button type="button" onClick={onToggleMode} className="hover:text-tx">
                {t("toRegister")}
              </button>
            ) : (
              <span />
            )}
            <Link href={pathFor(locale, "/auth/forgot")} className="hover:text-tx">
              {t("forgot")}
            </Link>
          </>
        ) : onToggleMode ? (
          <button type="button" onClick={onToggleMode} className="hover:text-tx">
            {t("toLogin")}
          </button>
        ) : null}
      </div>

      {showTelegram && (
        <>
          <div className="border-border/70 my-2 border-t" />
          <TelegramLoginButton />
        </>
      )}
    </form>
  );
}
