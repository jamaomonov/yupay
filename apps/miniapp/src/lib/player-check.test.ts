import { describe, expect, it, vi } from "vitest";

import { checkPlayer } from "./player-check";

import type * as ApiModule from "./api";

/**
 * Deferred finding #19: nothing pinned the URL `checkPlayer` posts to, or
 * that it goes through `apiPost` with `anonymous: true` — a public advisory
 * lookup that must never carry a bearer token.
 *
 * Mocks only `apiPost` and keeps every other export of `./api` real via
 * `importOriginal`, the same pattern `orders.test.ts` uses for the same
 * module.
 */
const mockApiPost =
  vi.fn<(path: string, body: unknown, opts?: Record<string, unknown>) => Promise<unknown>>();

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof ApiModule>();
  return {
    ...actual,
    apiPost: (path: string, body: unknown, opts?: Record<string, unknown>) =>
      mockApiPost(path, body, opts),
  };
});

describe("checkPlayer", () => {
  it("posts to the brand-scoped check-player endpoint", async () => {
    mockApiPost.mockResolvedValue({ status: "valid", name: "Neo" });

    await checkPlayer("mobile-legends-ru", { playerId: "1", serverId: "2" });

    expect(mockApiPost).toHaveBeenCalledWith(
      "/api/v1/catalog/brands/mobile-legends-ru/check-player",
      { player_id: "1", server_id: "2" },
      { anonymous: true },
    );
  });

  it("percent-encodes a slug that needs it", async () => {
    mockApiPost.mockResolvedValue({ status: "unsupported", name: null });

    await checkPlayer("a b", { playerId: "1", serverId: null });

    expect(mockApiPost).toHaveBeenCalledWith(
      "/api/v1/catalog/brands/a%20b/check-player",
      { player_id: "1", server_id: null },
      { anonymous: true },
    );
  });
});
