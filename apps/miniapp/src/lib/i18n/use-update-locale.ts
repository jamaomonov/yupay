/**
 * Mutation that flips the user's UI locale (``users.locale`` on the backend).
 *
 * Optimistically patches the ``/auth/me`` cache so the whole UI re-renders in
 * the new language in the same frame. ``I18nProvider`` observes the changed
 * ``me.locale`` and refetches the catalog (names are localized server-side),
 * so this mutation only needs to reconcile ``me`` on settle.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Locale } from "@yupay/i18n";

import { apiPatch } from "@/lib/api";
import { type Me } from "@/lib/auth";

export function useUpdateLocale() {
  const qc = useQueryClient();
  return useMutation<Me, Error, Locale, { previous?: Me }>({
    mutationFn: async (locale) => apiPatch<Me>("/api/v1/users/me", { locale }),
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
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}
