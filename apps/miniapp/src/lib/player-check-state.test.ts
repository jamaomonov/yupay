import { describe, expect, test, vi } from "vitest";

import {
  blocksCheckout,
  canCheck,
  checkUnavailable,
  currentCheck,
  currentFieldCheck,
  runPlayerCheck,
  serverIdFor,
  type PlayerCheckVerdict,
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

/**
 * The freshness rule, tested here rather than by rendering: this app's suite
 * is node-env with no jsdom, and `TopUp` reads the same answer twice (the CTA
 * gate and the review screen's nickname) while `DynamicFields` reads it a
 * third time for the pill. Same convention as `walletPayState` /
 * `profileCheckState`.
 */
describe("currentCheck", () => {
  const verdict: PlayerCheckVerdict = {
    productId: "prod-ru",
    playerId: "1313232551",
    serverId: "6618",
    result: { status: "valid", name: "blood moon" },
  };

  test("reads the verdict back for the question it was asked", () => {
    expect(currentCheck(verdict, "prod-ru", "1313232551", "6618")).toEqual({
      status: "valid",
      name: "blood moon",
    });
  });

  test("drops it the moment the package points at another product", () => {
    // ADR-0048: Mobile Legends and Magic Chess sell one product per account
    // region, and switching between them keeps the typed id.
    expect(currentCheck(verdict, "prod-global", "1313232551", "6618")).toBeNull();
  });

  test("drops it the moment the id is edited, including trailing whitespace", () => {
    expect(currentCheck(verdict, "prod-ru", "1313232552", "6618")).toBeNull();
    // Not trimmed on purpose: the verdict answers for the literal text that
    // was sent, and `runPlayerCheck` sends the field's value untouched.
    expect(currentCheck(verdict, "prod-ru", "1313232551 ", "6618")).toBeNull();
  });

  test("drops it the moment the server is edited — the id was checked ON one", () => {
    expect(currentCheck(verdict, "prod-ru", "1313232551", "7001")).toBeNull();
    expect(currentCheck(verdict, "prod-ru", "1313232551", null)).toBeNull();
  });

  test("an invalid verdict is read back the same way — it blocks, so it must not evaporate", () => {
    const bad: PlayerCheckVerdict = { ...verdict, result: { status: "invalid", name: null } };
    expect(currentCheck(bad, "prod-ru", "1313232551", "6618")).toEqual({
      status: "invalid",
      name: null,
    });
  });

  test("nothing stored reads as nothing checked", () => {
    expect(currentCheck(null, "prod-ru", "1313232551", "6618")).toBeNull();
    expect(currentCheck(undefined, "prod-ru", "1313232551", "6618")).toBeNull();
  });
});

describe("serverIdFor", () => {
  const values = { player_id: "1313232551", server: "6618" };

  test("null when the field's check names no sibling", () => {
    expect(serverIdFor({ key: "player_id" }, values)).toBeNull();
    expect(serverIdFor({ key: "player_id", check: {} }, values)).toBeNull();
  });

  test("the sibling's current value when it names one", () => {
    expect(serverIdFor({ key: "player_id", check: { server_field: "server" } }, values)).toBe(
      "6618",
    );
  });

  test("null when the named sibling has nothing in it yet", () => {
    expect(serverIdFor({ key: "player_id", check: { server_field: "zone" } }, values)).toBeNull();
  });
});

describe("currentFieldCheck", () => {
  const field = { key: "player_id", check: { server_field: "server" } };
  const values = { player_id: "1313232551", server: "6618" };
  const verdicts: Record<string, PlayerCheckVerdict | null> = {
    player_id: {
      productId: "prod-ru",
      playerId: "1313232551",
      serverId: "6618",
      result: { status: "valid", name: "blood moon" },
    },
  };

  test("stands while the form still asks the same question", () => {
    expect(currentFieldCheck(verdicts, "prod-ru", values, field)).toEqual({
      status: "valid",
      name: "blood moon",
    });
    expect(blocksCheckout(currentFieldCheck(verdicts, "prod-ru", values, field))).toBe(false);
  });

  test("editing the server alone unverifies the account, and blocks", () => {
    // The whole point of keying on the server: the id collapses into a
    // confirmation pill while the server stays an ordinary editable field
    // beside it, so this edit is invisible in the pill. G2B resolves a player
    // *on a server*; a `{player_id, server}` pair nobody checked is how a
    // top-up lands on a stranger's account.
    const moved = { ...values, server: "7001" };
    expect(currentFieldCheck(verdicts, "prod-ru", moved, field)).toBeNull();
    expect(blocksCheckout(currentFieldCheck(verdicts, "prod-ru", moved, field))).toBe(true);
  });

  test("switching to the other region's product unverifies it too", () => {
    expect(currentFieldCheck(verdicts, "prod-global", values, field)).toBeNull();
    expect(blocksCheckout(currentFieldCheck(verdicts, "prod-global", values, field))).toBe(true);
  });

  test("editing the id unverifies it", () => {
    const retyped = { ...values, player_id: "1313232559" };
    expect(currentFieldCheck(verdicts, "prod-ru", retyped, field)).toBeNull();
  });

  test("a field with no check config never stands behind anything", () => {
    // `TopUp` calls this for every required field, including plain ones.
    expect(currentFieldCheck(verdicts, "prod-ru", values, { key: "player_id" })).toBeNull();
  });

  test("reads only its own field's verdict", () => {
    expect(currentFieldCheck(verdicts, "prod-ru", values, { key: "server" })).toBeNull();
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
