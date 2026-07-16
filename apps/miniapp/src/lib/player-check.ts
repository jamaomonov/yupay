/** Storefront player-id verification (advisory nickname lookup). */
import { apiPost } from "@/lib/api";

export interface PlayerCheckResult {
  valid: boolean;
  name: string | null;
  reason: string | null;
}

export function checkPlayer(
  productId: string,
  input: { playerId: string; serverId?: string | null },
): Promise<PlayerCheckResult> {
  return apiPost<PlayerCheckResult>(
    `/api/v1/catalog/products/${productId}/check-player`,
    { player_id: input.playerId, server_id: input.serverId ?? null },
    { anonymous: true },
  );
}
