/**
 * Mutation that sets (or clears) where this customer's order codes are mailed.
 *
 * A mini app account is a Telegram account: it has no email, so the delivery
 * mail an order produces had nowhere to go. This is the address it goes to.
 *
 * It is **not** the login identity. `users.email` carries a unique index and
 * three auth lookups resolve an account by it, so writing an unverified
 * address there from a settings screen would collide with a real account or
 * let someone claim an address a password reset later targets. The server
 * keeps them separate; this only ever touches `delivery_email`.
 *
 * An empty string clears it — the only way back to "use my account address".
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/hooks/use-toast";
import { apiPatch } from "@/lib/api";
import { type Me } from "@/lib/auth";
import { translate } from "@/lib/i18n/core";

/**
 * The PATCH body for a typed-in address.
 *
 * Its own function so the one thing worth pinning is testable without a React
 * renderer (the mini app's suite is pure-function only, and pulling in a DOM
 * testing library for this would be a new dependency and an ADR): the body
 * carries `delivery_email` and never `email`. Writing the login identity from
 * a settings screen would collide with a real account's unique index, or let
 * someone claim an address a password reset later targets.
 *
 * Trimmed, and an empty string is preserved rather than dropped — the server
 * reads it as "clear it", which is the only way back to the account address.
 */
export function deliveryEmailPatch(raw: string): { delivery_email: string } {
  return { delivery_email: raw.trim() };
}

export function useUpdateDeliveryEmail() {
  const qc = useQueryClient();
  const { toast } = useToast();
  return useMutation<Me, Error, string, { previous?: Me }>({
    mutationFn: (email) => apiPatch<Me>("/api/v1/users/me", deliveryEmailPatch(email)),
    onMutate: async (email) => {
      await qc.cancelQueries({ queryKey: ["me"] });
      const previous = qc.getQueryData<Me>(["me"]);
      if (previous) {
        qc.setQueryData<Me>(["me"], { ...previous, delivery_email: email || null });
      }
      return { previous };
    },
    onError: (_err, _vars, ctx) => {
      // Revert rather than leave the screen showing an address we did not save
      // — the customer would go on believing their codes have somewhere to go.
      if (ctx?.previous) qc.setQueryData(["me"], ctx.previous);
      toast({ title: translate("settings.emailSaveFailed"), variant: "destructive" });
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}
