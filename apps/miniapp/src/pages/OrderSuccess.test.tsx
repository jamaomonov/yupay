import { describe, expect, it } from "vitest";

import { isGiftDelivery, pickArtifactDisplay, providerIcon, providerLabel } from "./OrderSuccess";

import type { DeliveryOut } from "@/lib/orders";

import { translate } from "@/lib/i18n/core";

describe("providerLabel", () => {
  it("maps click (and click_miniapp) to the Click brand name", () => {
    expect(providerLabel("click")).toBe("Click");
    expect(providerLabel("click_miniapp")).toBe("Click");
  });

  it("maps payme, uzum and octo to their brand names", () => {
    expect(providerLabel("payme")).toBe("Payme");
    expect(providerLabel("uzum")).toBe("Uzum");
    expect(providerLabel("octo")).toBe("Octo");
  });

  it("maps wallet to the localized balance label", () => {
    expect(providerLabel("wallet")).toBe(translate("success.paidWithWallet"));
  });

  it("renders an unknown slug as-is and null/empty as null", () => {
    expect(providerLabel("mock")).toBe("mock");
    expect(providerLabel(null)).toBeNull();
    expect(providerLabel("")).toBeNull();
  });
});

describe("providerIcon", () => {
  it("resolves a brand mark for click (and click_miniapp), payme and uzum", () => {
    for (const slug of ["click", "click_miniapp", "payme", "uzum"]) {
      expect(providerIcon(slug)).toEqual(expect.any(String));
    }
  });

  it("returns null for providers with no asset, and for null/empty", () => {
    expect(providerIcon("wallet")).toBeNull();
    expect(providerIcon("octo")).toBeNull();
    expect(providerIcon("mock")).toBeNull();
    expect(providerIcon(null)).toBeNull();
    expect(providerIcon("")).toBeNull();
  });
});

describe("pickArtifactDisplay", () => {
  it("prefers code over every other whitelisted key", () => {
    expect(pickArtifactDisplay({ code: "ABC-123", key: "K", message: "hi" })).toEqual({
      kind: "copyable",
      artifactKey: "code",
      value: "ABC-123",
    });
  });

  it("falls back to key when there is no code", () => {
    expect(pickArtifactDisplay({ key: "SECRET-KEY" })).toEqual({
      kind: "copyable",
      artifactKey: "key",
      value: "SECRET-KEY",
    });
  });

  // Regression: an admin-manual-completion (e.g. handing over a Steam
  // account) or a G2B-style receipt has no code/key at all — the artifact's
  // only content is steam_login/login. ArtifactBlock used to derive its
  // fallback line from `artifact.external_id`, which the Phase 1 whitelist
  // strips server-side, so this case rendered only the generic "credited"
  // line with no actual account info.
  it("shows steam_login when there is no code/key", () => {
    expect(pickArtifactDisplay({ steam_login: "player123" })).toEqual({
      kind: "copyable",
      artifactKey: "steam_login",
      value: "player123",
    });
  });

  it("shows login when there is no code/key/steam_login", () => {
    expect(pickArtifactDisplay({ login: "someone@example.com" })).toEqual({
      kind: "copyable",
      artifactKey: "login",
      value: "someone@example.com",
    });
  });

  it("falls back to a free-text message when no copyable key is present", () => {
    expect(pickArtifactDisplay({ message: "Account handed over via support chat" })).toEqual({
      kind: "text",
      value: "Account handed over via support chat",
    });
  });

  it("falls back to note when there is no message", () => {
    expect(pickArtifactDisplay({ note: "See attached receipt" })).toEqual({
      kind: "text",
      value: "See attached receipt",
    });
  });

  it("falls back to fulfillment_data scalar entries when nothing else is present", () => {
    expect(pickArtifactDisplay({ fulfillment_data: { player_id: "PID-1", region: "" } })).toEqual({
      kind: "fields",
      entries: [["player_id", "PID-1"]],
    });
  });

  it("never reads external_id — it is not part of the customer-safe whitelist", () => {
    expect(pickArtifactDisplay({ external_id: "mock_abc123" })).toEqual({ kind: "empty" });
  });

  it("returns empty for an artifact with no renderable whitelisted content", () => {
    expect(pickArtifactDisplay({})).toEqual({ kind: "empty" });
    expect(pickArtifactDisplay({ message: null, fulfillment_data: {} })).toEqual({
      kind: "empty",
    });
  });
});

describe("isGiftDelivery", () => {
  function makeDelivery(artifact: Record<string, unknown>): DeliveryOut {
    return {
      id: "delivery-1",
      order_item_id: "item-1",
      channel: "bot",
      // The gengine gift fulfiller reports `artifact_kind: "topup_receipt"`
      // (see `gengine_gifts.py::_map_gift_order`) — the gift/non-gift signal
      // lives inside the artifact's own `kind` field, not this enum.
      artifact_kind: "topup_receipt",
      artifact,
      delivered_at: "2026-09-03T12:00:00Z",
    };
  }

  it("is true when the artifact's own kind is gift", () => {
    expect(
      isGiftDelivery(
        makeDelivery({ kind: "gift", app_name: "Dead Cells", package_name: "Dead Cells" }),
      ),
    ).toBe(true);
  });

  it("is false for a top-up receipt artifact (no kind field)", () => {
    expect(isGiftDelivery(makeDelivery({ external_id: "abc" }))).toBe(false);
  });

  it("is false for a voucher/license artifact (a different kind)", () => {
    expect(isGiftDelivery(makeDelivery({ code: "ABC-123" }))).toBe(false);
  });

  it("is false for null (no delivery yet)", () => {
    expect(isGiftDelivery(null)).toBe(false);
  });
});
