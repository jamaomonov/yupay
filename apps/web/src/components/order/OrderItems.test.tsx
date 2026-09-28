// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, it } from "vitest";

import { OrderItems } from "./OrderItems";

import type { OrderItemDisplay, OrderItemOut } from "@/lib/orders-types";
import type { ReactNode } from "react";

const messages = {
  web: {
    orders: {
      itemsTitle: "Order composition",
      qty: "Qty",
      receipt: {
        steam_login: "Steam login",
        login: "Login",
        float_value: "Float",
      },
    },
  },
};

function wrap(ui: ReactNode) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      {ui}
    </NextIntlClientProvider>,
  );
}

function display(over: Partial<OrderItemDisplay>): OrderItemDisplay {
  return {
    brand_slug: "steam",
    brand_name: "Steam",
    product_slug: "steam-wallet",
    product_name: "Steam Wallet",
    product_kind: "top_up",
    sku_code: "STEAM-VAR",
    denomination: null,
    region: null,
    image_url: null,
    variable_amount: true,
    ...over,
  };
}

function item(over: Partial<OrderItemOut>): OrderItemOut {
  return {
    id: "item-1",
    sku_id: "sku-1",
    qty: 1,
    unit_price_usd: "11.30",
    fulfillment_state: "delivered",
    fulfillment_data: {},
    display: display({}),
    ...over,
  };
}

it("shows the credited USD amount for a variable-amount top-up (no denomination)", () => {
  wrap(<OrderItems items={[item({ fulfillment_data: { steam_login: "_jamshid__" } })]} />);
  // Brand + amount read as one line: "Steam · $11.30".
  expect(screen.getByText("Steam · $11.30")).toBeInTheDocument();
});

it("shows the amount, not a digit-free placeholder denomination (Любая сумма)", () => {
  wrap(<OrderItems items={[item({ display: display({ denomination: "Любая сумма" }) })]} />);
  expect(screen.getByText("Steam · $11.30")).toBeInTheDocument();
  expect(screen.queryByText(/Любая сумма/)).not.toBeInTheDocument();
});

it("renders the target account (checkout input) as a labeled row, not a delivery", () => {
  wrap(<OrderItems items={[item({ fulfillment_data: { steam_login: "_jamshid__" } })]} />);
  expect(screen.getByText("Steam login")).toBeInTheDocument();
  expect(screen.getByText("_jamshid__")).toBeInTheDocument();
});

it("multiplies the unit price by qty for the amount and shows a qty chip", () => {
  wrap(<OrderItems items={[item({ qty: 2, unit_price_usd: "5.15" })]} />);
  expect(screen.getByText("Steam · $10.30")).toBeInTheDocument();
  expect(screen.getByText("Qty: 2")).toBeInTheDocument();
});

it("humanizes an unknown checkout field name", () => {
  wrap(<OrderItems items={[item({ fulfillment_data: { player_id: "77" } })]} />);
  expect(screen.getByText("Player Id")).toBeInTheDocument();
  expect(screen.getByText("77")).toBeInTheDocument();
});

it("prefers a fixed denomination over the USD amount", () => {
  wrap(
    <OrderItems
      items={[item({ display: display({ denomination: "820 UC", variable_amount: false }) })]}
    />,
  );
  expect(screen.getByText("Steam · 820 UC")).toBeInTheDocument();
  expect(screen.queryByText(/\$11\.30/)).not.toBeInTheDocument();
});

it("shows a skin as the skin bought, with its float and none of the checkout internals", () => {
  wrap(
    <OrderItems
      items={[
        item({
          unit_price_usd: "30.00",
          display: display({
            brand_name: "CS2 скины",
            product_name: "CS2 скины",
            sku_code: "cs2-skin",
            denomination: "AK-47 | Redline (Field-Tested)",
            variable_amount: false,
          }),
          fulfillment_data: {
            slug: "ak-47-redline-field-tested",
            listing_id: 53644184708,
            tradelink: "https://steamcommunity.com/tradeoffer/new/?partner=1&token=abcdefgh",
            name: "AK-47 | Redline (Field-Tested)",
            waxpeer_name: "AK-47 | Redline (Field-Tested)",
            float_value: 0.2134,
          },
        }),
      ]}
    />,
  );
  expect(screen.getByText("CS2 скины · AK-47 | Redline (Field-Tested)")).toBeInTheDocument();
  expect(screen.getByText("Float")).toBeInTheDocument();
  expect(screen.queryByText(/tradeoffer/)).not.toBeInTheDocument();
  expect(screen.queryByText("Listing Id")).not.toBeInTheDocument();
  expect(screen.queryByText("Waxpeer Name")).not.toBeInTheDocument();
});
