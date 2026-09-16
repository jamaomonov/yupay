import { describe, expect, test, vi } from "vitest";

import {
  blocksCheckout,
  canCheck,
  checkBlocker,
  checkUnavailable,
  currentCheck,
  runPlayerCheck,
} from "./player-check-state";

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
    expect(s).toEqual({ status: "valid", name: "Neo" });
    expect(run).toHaveBeenCalledWith("p1", { playerId: "51234567" });
  });
  test("passes an invalid result through unchanged (not folded to error)", async () => {
    const run = vi.fn().mockResolvedValue({ status: "invalid", name: null });
    const s = await runPlayerCheck("p1", { playerId: "9" }, run);
    expect(s).toEqual({ status: "invalid", name: null });
  });
  test("folds a thrown error into status=error, never invalid", async () => {
    const run = vi.fn().mockRejectedValue(new Error("network"));
    const s = await runPlayerCheck("p1", { playerId: "9" }, run);
    expect(s).toEqual({ status: "error", name: null });
  });
  test("passes serverId through", async () => {
    const run = vi.fn().mockResolvedValue({ status: "invalid", name: null });
    await runPlayerCheck("p1", { playerId: "9", serverId: "as" }, run);
    expect(run).toHaveBeenCalledWith("p1", { playerId: "9", serverId: "as" });
  });
});

describe("checkBlocker", () => {
  const server = { required: true, id: "6618" };

  test("names the missing player id rather than just refusing", () => {
    expect(checkBlocker({ value: "", server })).toBe("playerId");
  });

  test("blocks on a filled server id with an empty player id", () => {
    // The asymmetry reported from prod: this direction used to run the check.
    expect(checkBlocker({ value: "  ", pattern: "^[0-9]{5,20}$", server })).toBe("playerId");
  });

  test("blocks on a filled player id with an empty server id", () => {
    expect(checkBlocker({ value: "1313232551", server: { required: true, id: "" } })).toBe(
      "serverId",
    );
  });

  test("passes when both halves are present", () => {
    expect(checkBlocker({ value: "1313232551", server })).toBeNull();
  });

  test("treats a value that fails the field's pattern as a missing id", () => {
    expect(checkBlocker({ value: "12", pattern: "^[0-9]{5,20}$", server })).toBe("playerId");
  });

  test("lets a malformed server-supplied pattern through rather than blocking", () => {
    expect(checkBlocker({ value: "1313232551", pattern: "([", server })).toBeNull();
  });

  test("ignores the server half when no sibling field is named", () => {
    expect(checkBlocker({ value: "_jamshid__", server: { required: false, id: null } })).toBeNull();
  });
});

describe("currentCheck", () => {
  const verdict = {
    brandSlug: "mobile-legends-ru",
    playerId: "1313232551",
    serverId: "6618",
    result: { status: "valid" as const, name: "blood moon" },
  };

  test("reads the verdict back for the question it was asked", () => {
    expect(currentCheck(verdict, "mobile-legends-ru", "1313232551", "6618")).toEqual({
      status: "valid",
      name: "blood moon",
    });
  });

  test("drops it the moment the package points at another brand", () => {
    // ADR-0079: a brand is one game, so a region split (MLBB global vs RU) is
    // two brands now, not two products of one. Shown against the other
    // brand, a green pill is reassurance for an account nobody is paying for.
    expect(currentCheck(verdict, "mobile-legends", "1313232551", "6618")).toBeNull();
  });

  test("drops it the moment the id is edited, including trailing whitespace", () => {
    expect(currentCheck(verdict, "mobile-legends-ru", "1313232552", "6618")).toBeNull();
    // Not trimmed on purpose: the verdict answers for the literal text that
    // was sent, and `runPlayerCheck` sends the field's value untouched.
    expect(currentCheck(verdict, "mobile-legends-ru", "1313232551 ", "6618")).toBeNull();
  });

  test("drops it the moment the server is edited — the id was checked ON one", () => {
    // The half the id alone cannot cover: G2B resolves a player *on a server*,
    // and the MLBB form leaves the server editable beside the confirmed id, so
    // this is the difference between a verified account and a stranger's.
    expect(currentCheck(verdict, "mobile-legends-ru", "1313232551", "7001")).toBeNull();
    expect(currentCheck(verdict, "mobile-legends-ru", "1313232551", null)).toBeNull();
  });

  test("a field with no sibling server keeps its null-for-null match", () => {
    const noServer = { ...verdict, serverId: null };
    expect(currentCheck(noServer, "mobile-legends-ru", "1313232551", null)).toEqual({
      status: "valid",
      name: "blood moon",
    });
  });

  test("an invalid verdict is read back the same way — it blocks, so it must not evaporate", () => {
    const bad = { ...verdict, result: { status: "invalid" as const, name: null } };
    expect(currentCheck(bad, "mobile-legends-ru", "1313232551", "6618")).toEqual({
      status: "invalid",
      name: null,
    });
  });

  test("nothing stored reads as nothing checked", () => {
    expect(currentCheck(null, "mobile-legends-ru", "1313232551", "6618")).toBeNull();
    expect(currentCheck(undefined, "mobile-legends-ru", "1313232551", "6618")).toBeNull();
  });
});

describe("blocksCheckout", () => {
  test("an unchecked id blocks", () => {
    expect(blocksCheckout(undefined)).toBe(true);
    expect(blocksCheckout(null)).toBe(true);
  });
  test("a valid id does not block", () =>
    expect(blocksCheckout({ status: "valid", name: "Neo" })).toBe(false));
  test("an invalid id blocks — the provider said no such player", () =>
    expect(blocksCheckout({ status: "invalid", name: null })).toBe(true));
  test("a failed check does NOT block: the outage is ours, not the customer's", () =>
    expect(blocksCheckout({ status: "error", name: null })).toBe(false));
});

describe("checkUnavailable", () => {
  test("only error asks the customer to re-read the id", () => {
    expect(checkUnavailable({ status: "error", name: null })).toBe(true);
    expect(checkUnavailable({ status: "invalid", name: null })).toBe(false);
    expect(checkUnavailable({ status: "valid", name: "Neo" })).toBe(false);
    expect(checkUnavailable(undefined)).toBe(false);
  });
});
