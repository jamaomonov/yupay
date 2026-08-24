"use client";

import { useTranslations } from "next-intl";
import { useCallback } from "react";

import { useAuth } from "@/lib/auth";
import { useLoginModal } from "@/store/useLoginModal";
import { toast } from "@/store/useToast";

/**
 * What happens after Telegram hands back a signed user.
 *
 * Both Telegram entry points used to be written as `void loginWithTelegram(u)`,
 * which threw the outcome away: on success the modal stayed open over a
 * storefront that had quietly signed the customer in, and on failure nothing
 * appeared at all — the tile just did nothing twice in a row. Email sign-in
 * closed the modal but also said nothing.
 *
 * Shared rather than repeated at each call site because there are two of them
 * today (the popup tile and the official widget) and the Google/Steam tiles are
 * marked "soon" — the next provider should inherit this instead of rediscovering
 * it.
 *
 * The modal closes only on success. A failure leaves it open, because the
 * customer still has to get in and the other methods are behind it.
 */
export function useTelegramSignIn(): (user: Record<string, unknown>) => void {
  const { loginWithTelegram } = useAuth();
  const close = useLoginModal((s) => s.close);
  const t = useTranslations("web.auth");

  return useCallback(
    (user: Record<string, unknown>) => {
      void loginWithTelegram(user)
        .then(() => {
          close();
          toast.success(t("signedIn"));
        })
        .catch(() => {
          toast.error(t("signInFailed"));
        });
    },
    [loginWithTelegram, close, t],
  );
}
