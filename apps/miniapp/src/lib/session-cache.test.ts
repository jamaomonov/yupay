import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { discardPreSessionMe } from "./auth";

/**
 * The reported bug: opening the mini app sometimes landed the customer signed
 * out, and only a reload or a reopen fixed it.
 *
 * `I18nProvider` sits *above* `BootstrapGate` and calls `useMe()`, whose
 * `queryFn` answers `null` when no token is stored yet. On a cold launch that
 * answer is cached before the Telegram login has finished — with
 * `staleTime: 60_000`. The gate then warms `["me"]` with the same staleTime,
 * finds a fresh `null`, and skips the fetch entirely. The app is released with
 * a cached signed-out answer that stays fresh for a minute.
 */
describe("a `me` answered before the session existed", () => {
  it("makes the gate's warm-up a no-op", async () => {
    const qc = new QueryClient();
    let fetched = 0;

    // I18nProvider, before the token lands.
    await qc.fetchQuery({
      queryKey: ["me"],
      queryFn: () => Promise.resolve(null),
      staleTime: 60_000,
    });

    // The gate, after logging in.
    await qc.fetchQuery({
      queryKey: ["me"],
      queryFn: () => {
        fetched += 1;
        return Promise.resolve({ id: "user-1" });
      },
      staleTime: 60_000,
    });

    expect(fetched).toBe(0);
    expect(qc.getQueryData(["me"])).toBeNull();
  });

  it("is discarded, so the warm-up really fetches", async () => {
    const qc = new QueryClient();
    let fetched = 0;

    await qc.fetchQuery({
      queryKey: ["me"],
      queryFn: () => Promise.resolve(null),
      staleTime: 60_000,
    });

    // What the gate now does the moment a fresh session exists.
    discardPreSessionMe(qc);

    const warmed = await qc.fetchQuery({
      queryKey: ["me"],
      queryFn: () => {
        fetched += 1;
        return Promise.resolve({ id: "user-1" });
      },
      staleTime: 60_000,
    });

    expect(fetched).toBe(1);
    expect(warmed).toEqual({ id: "user-1" });
  });
});
