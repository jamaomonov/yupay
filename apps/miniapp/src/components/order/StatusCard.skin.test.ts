import { describe, expect, it } from "vitest";

import { stageFor } from "./StatusCard";

import type { OrderOut, OrderStatus } from "@/lib/orders";

import { translate } from "@/lib/i18n/core";

const skinOrder = (status: OrderStatus): OrderOut =>
  ({
    id: "o1",
    status,
    currency: "UZS",
    items: [
      {
        id: "i1",
        display: { product_kind: "top_up" },
        skin_trade: {
          state: "buying",
          offer_url: null,
          send_until: null,
          release_date: null,
          seller: null,
          reason_code: null,
        },
      },
    ],
  }) as unknown as OrderOut; // only the fields stageFor reads

describe("stageFor — a CS2 skin order", () => {
  it("never says an account is being credited", () => {
    expect(stageFor(skinOrder("fulfilling")).subtitle).toBe(
      translate("success.stage.fulfillingSubSkin"),
    );
  });

  it("says a refund went to the YuPay balance, not the card", () => {
    expect(stageFor(skinOrder("refunded")).subtitle).toBe(
      translate("success.stage.refundedSubSkin"),
    );
  });

  it("never promises a card refund for a failed skin", () => {
    expect(stageFor(skinOrder("failed")).subtitle).toBe(translate("success.stage.failedSubSkin"));
  });
});
