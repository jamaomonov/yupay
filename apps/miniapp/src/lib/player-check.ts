/** Storefront player-id verification (advisory nickname lookup). */
import { apiPost } from "@/lib/api";

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
  brandSlug: string,
  input: { playerId: string; serverId?: string | null },
): Promise<PlayerCheckResult> {
  return apiPost<PlayerCheckResult>(
    `/api/v1/catalog/brands/${encodeURIComponent(brandSlug)}/check-player`,
    { player_id: input.playerId, server_id: input.serverId ?? null },
    { anonymous: true },
  );
}
