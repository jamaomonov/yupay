import { expect, it, vi } from "vitest";

import { checkPlayer } from "./player-check";

import { apiFetch } from "@/lib/client";

/**
 * Deferred finding #19: nothing pinned the URL `checkPlayer` posts to, or
 * that it goes to `apiFetch` (not `fetch` directly) with `anonymous: true` —
 * a public advisory lookup that must never carry a bearer token.
 *
 * `apiFetch` lives in `@/lib/client` (not `@/lib/api`, which is the
 * miniapp's module of the same name) — that's what `player-check.ts`
 * actually imports.
 */
vi.mock("@/lib/client", () => ({ apiFetch: vi.fn() }));

const mockApiFetch = vi.mocked(apiFetch);

it("posts to the brand-scoped check-player endpoint", async () => {
  mockApiFetch.mockResolvedValue({ status: "valid", name: "Neo" });

  await checkPlayer("mobile-legends-ru", { playerId: "1", serverId: "2" });

  expect(apiFetch).toHaveBeenCalledWith(
    "/catalog/brands/mobile-legends-ru/check-player",
    expect.objectContaining({
      method: "POST",
      body: { player_id: "1", server_id: "2" },
      anonymous: true,
    }),
  );
});

it("percent-encodes a slug that needs it", async () => {
  mockApiFetch.mockResolvedValue({ status: "unsupported", name: null });

  await checkPlayer("a b", { playerId: "1", serverId: null });

  expect(apiFetch).toHaveBeenCalledWith(
    "/catalog/brands/a%20b/check-player",
    expect.objectContaining({
      method: "POST",
      body: { player_id: "1", server_id: null },
      anonymous: true,
    }),
  );
});
