"use client";

import { useTranslations } from "next-intl";
import { useCallback } from "react";

import { useAuth } from "@/lib/auth";
import { useLoginModal } from "@/store/useLoginModal";
import { toast } from "@/store/useToast";

/**
 * What happens after Google hands back a signed credential — the same
 * contract `useTelegramSignIn` established: success closes the modal and
 * says so, failure keeps the modal open (the customer still has to get in,
 * and the other methods are behind it).
 */
export function useGoogleSignIn(): (credential: string) => void {
  const { loginWithGoogle } = useAuth();
  const close = useLoginModal((s) => s.close);
  const t = useTranslations("web.auth");

  return useCallback(
    (credential: string) => {
      void loginWithGoogle(credential)
        .then(() => {
          close();
          toast.success(t("signedIn"));
        })
        .catch(() => {
          toast.error(t("signInFailed"));
        });
    },
    [loginWithGoogle, close, t],
  );
}
