/** Storefront player-id verification (advisory nickname lookup). */
import { apiFetch } from "@/lib/client";

/** Three-way outcome from the backend (see PlayerCheckOut):
 *  - `valid`   → `name` is the account nickname
 *  - `invalid` → the id doesn't resolve (customer mistyped it)
 *  - `error`   → our/provider fault; never blame the customer */
export type PlayerCheckStatus = "valid" | "invalid" | "error";

export interface PlayerCheckResult {
  status: PlayerCheckStatus;
  name: string | null;
}

export function checkPlayer(
  productId: string,
  input: { playerId: string; serverId?: string | null },
): Promise<PlayerCheckResult> {
  return apiFetch<PlayerCheckResult>(`/catalog/products/${productId}/check-player`, {
    method: "POST",
    body: { player_id: input.playerId, server_id: input.serverId ?? null },
    anonymous: true,
  });
}
