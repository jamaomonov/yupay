import { describe, expect, test, vi } from "vitest";

import { canCheck, runPlayerCheck } from "./player-check-state";

describe("canCheck", () => {
  test("false when blank", () => expect(canCheck("   ")).toBe(false));
  test("true when non-empty and no pattern", () => expect(canCheck("51234567")).toBe(true));
  test("false when pattern does not match", () =>
    expect(canCheck("abc", "^[0-9]{6,15}$")).toBe(false));
  test("true when pattern matches", () => expect(canCheck("51234567", "^[0-9]{6,15}$")).toBe(true));
  test("malformed pattern does not block the user", () => expect(canCheck("x", "([")).toBe(true));
});

describe("runPlayerCheck", () => {
  test("passes a valid result through", async () => {
    const run = vi.fn().mockResolvedValue({ status: "valid", name: "Neo" });
    const s = await runPlayerCheck("p1", { playerId: "51234567" }, run);
    expect(s).toEqual({ phase: "done", result: { status: "valid", name: "Neo" } });
    expect(run).toHaveBeenCalledWith("p1", { playerId: "51234567" });
  });
  test("passes an invalid result through unchanged (not folded to error)", async () => {
    const run = vi.fn().mockResolvedValue({ status: "invalid", name: null });
    const s = await runPlayerCheck("p1", { playerId: "9" }, run);
    expect(s).toEqual({ phase: "done", result: { status: "invalid", name: null } });
  });
  test("folds a thrown error into status=error, never invalid", async () => {
    const run = vi.fn().mockRejectedValue(new Error("network"));
    const s = await runPlayerCheck("p1", { playerId: "9" }, run);
    expect(s).toEqual({ phase: "done", result: { status: "error", name: null } });
  });
  test("passes serverId through", async () => {
    const run = vi.fn().mockResolvedValue({ status: "invalid", name: null });
    await runPlayerCheck("p1", { playerId: "9", serverId: "as" }, run);
    expect(run).toHaveBeenCalledWith("p1", { playerId: "9", serverId: "as" });
  });
});
