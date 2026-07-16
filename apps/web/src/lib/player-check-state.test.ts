import { describe, expect, test, vi } from "vitest";

import { canCheck, runPlayerCheck } from "./player-check-state";

describe("canCheck", () => {
  test("false when blank", () => expect(canCheck("   ")).toBe(false));
  test("true when non-empty and no pattern", () => expect(canCheck("51234567")).toBe(true));
  test("false when pattern does not match", () =>
    expect(canCheck("abc", "^[0-9]{6,15}$")).toBe(false));
  test("true when pattern matches", () =>
    expect(canCheck("51234567", "^[0-9]{6,15}$")).toBe(true));
  test("malformed pattern does not block the user", () => expect(canCheck("x", "([")).toBe(true));
});

describe("runPlayerCheck", () => {
  test("done with result on success", async () => {
    const run = vi.fn().mockResolvedValue({ valid: true, name: "Neo", reason: null });
    const s = await runPlayerCheck("p1", { playerId: "51234567" }, run);
    expect(s).toEqual({ phase: "done", result: { valid: true, name: "Neo", reason: null } });
    expect(run).toHaveBeenCalledWith("p1", { playerId: "51234567" });
  });
  test("folds a thrown error into an advisory soft-failure", async () => {
    const run = vi.fn().mockRejectedValue(new Error("network"));
    const s = await runPlayerCheck("p1", { playerId: "9" }, run);
    expect(s).toEqual({ phase: "done", result: { valid: false, name: null, reason: null } });
  });
  test("passes serverId through", async () => {
    const run = vi.fn().mockResolvedValue({ valid: false, name: null, reason: "x" });
    await runPlayerCheck("p1", { playerId: "9", serverId: "as" }, run);
    expect(run).toHaveBeenCalledWith("p1", { playerId: "9", serverId: "as" });
  });
});
