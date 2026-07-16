/** Storefront player-id verification (advisory nickname lookup). */
import { apiFetch } from "@/lib/client";

export interface PlayerCheckResult {
  valid: boolean;
  name: string | null;
  reason: string | null;
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
