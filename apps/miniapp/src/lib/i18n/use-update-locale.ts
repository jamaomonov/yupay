/**
 * Mutation that flips the user's UI locale.
 *
 * Authenticated: persisted server-side (``users.locale``) with an optimistic
 * patch of the ``/auth/me`` cache; ``I18nProvider`` observes ``me.locale`` and
 * refetches the catalog (names are localized server-side).
 *
 * Anonymous (plain browser / pre-auth): there is no ``me`` to patch and the
 * PATCH would 401 — the choice is applied to the local mirror and persisted in
 * localStorage instead, so it survives a relaunch.
 *
 * Both paths persist locally; a failed server save reverts and surfaces a
 * toast instead of silently snapping back to the old language.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Locale } from "@yupay/i18n";

import { useToast } from "@/hooks/use-toast";
import { apiPatch, getAccessToken } from "@/lib/api";
import { type Me } from "@/lib/auth";

import { persistLocale, setActiveLocale, translate } from "./core";

export function useUpdateLocale() {
  const qc = useQueryClient();
  const { toast } = useToast();
  return useMutation<Me | null, Error, Locale, { previous?: Me }>({
    mutationFn: async (locale) => {
      persistLocale(locale);
      if (!getAccessToken()) {
        // Anonymous: local-only switch, nothing to save server-side.
        setActiveLocale(locale);
        return null;
      }
      return apiPatch<Me>("/api/v1/users/me", { locale });
    },
    onMutate: async (locale) => {
      await qc.cancelQueries({ queryKey: ["me"] });
      const previous = qc.getQueryData<Me>(["me"]);
      if (previous) {
        qc.setQueryData<Me>(["me"], { ...previous, locale });
      }
      return { previous };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) qc.setQueryData(["me"], ctx.previous);
      toast({ title: translate("settings.langSaveFailed"), variant: "destructive" });
    },
    onSettled: (_data, _err) => {
      if (getAccessToken()) void qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}
