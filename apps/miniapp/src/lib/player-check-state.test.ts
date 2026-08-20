import { describe, expect, test, vi } from "vitest";

import { canCheck, mergeCheckResult, runPlayerCheck } from "./player-check-state";

describe("canCheck", () => {
  test("false when blank", () => expect(canCheck("   ")).toBe(false));
  test("true when non-empty and no pattern", () => expect(canCheck("51234567")).toBe(true));
  test("false when pattern does not match", () =>
    expect(canCheck("abc", "^[0-9]{6,15}$")).toBe(false));
  test("true when pattern matches", () => expect(canCheck("51234567", "^[0-9]{6,15}$")).toBe(true));
  test("malformed pattern does not block the user", () => expect(canCheck("x", "([")).toBe(true));
  test("true when server not required, even with no id", () =>
    expect(canCheck("51234567", null, { required: false, id: null })).toBe(true));
  test("false when server required and empty", () =>
    expect(canCheck("51234567", null, { required: true, id: "" })).toBe(false));
  test("false when server required and null", () =>
    expect(canCheck("51234567", null, { required: true, id: null })).toBe(false));
  test("true when server required and filled in", () =>
    expect(canCheck("51234567", null, { required: true, id: "19450" })).toBe(true));
  test("still false on a blank id even with a filled-in server", () =>
    expect(canCheck("   ", null, { required: true, id: "19450" })).toBe(false));
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

describe("mergeCheckResult", () => {
  test("sets a new key's result", () => {
    const next = mergeCheckResult({}, "player_id", { status: "valid", name: "Neo" });
    expect(next).toEqual({ player_id: { status: "valid", name: "Neo" } });
  });

  test("returns the very same reference when both idle (null → null)", () => {
    const prev = {};
    expect(mergeCheckResult(prev, "player_id", null)).toBe(prev);
  });

  test("returns the very same reference when the result is unchanged", () => {
    const prev = { player_id: { status: "valid" as const, name: "Neo" } };
    const next = mergeCheckResult(prev, "player_id", { status: "valid", name: "Neo" });
    expect(next).toBe(prev);
  });

  test("returns a new object when the status changes", () => {
    const prev = { player_id: { status: "valid" as const, name: "Neo" } };
    const next = mergeCheckResult(prev, "player_id", { status: "invalid", name: null });
    expect(next).not.toBe(prev);
    expect(next).toEqual({ player_id: { status: "invalid", name: null } });
  });

  test("returns a new object when a fresh field key is edited back to idle", () => {
    const prev = { player_id: { status: "valid" as const, name: "Neo" } };
    const next = mergeCheckResult(prev, "player_id", null);
    expect(next).not.toBe(prev);
    expect(next).toEqual({ player_id: null });
  });

  test("leaves other keys untouched", () => {
    const prev = { server: { status: "valid" as const, name: "S1" } };
    const next = mergeCheckResult(prev, "player_id", { status: "valid", name: "Neo" });
    expect(next).toEqual({
      server: { status: "valid", name: "S1" },
      player_id: { status: "valid", name: "Neo" },
    });
  });
});
