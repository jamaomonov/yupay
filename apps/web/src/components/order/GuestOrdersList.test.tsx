// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, it } from "vitest";

import { GuestOrdersList } from "./GuestOrdersList";

import type { GuestOrder } from "@/lib/guest-orders";
import type { ReactNode } from "react";

const messages = {
  web: {
    orders: {
      guestListTitle: "Your orders",
      guestListEmpty: "No orders on this device yet.",
      guestListHint: "Orders on this device",
      toCatalog: "Browse catalog",
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

it("shows the empty state with a catalog link when there are no guest orders", () => {
  wrap(<GuestOrdersList orders={[]} locale="en" />);
  expect(screen.getByText("No orders on this device yet.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Browse catalog" })).toHaveAttribute("href", "/en/store");
});

it("renders a card per guest order with the brand name and a formatted date", () => {
  const createdAt = "2026-07-01T00:00:00.000Z";
  const orders: GuestOrder[] = [
    {
      orderId: "o1",
      email: "buyer@example.com",
      brandSlug: "pubg",
      brandName: "PUBG Mobile",
      createdAt,
    },
  ];
  wrap(<GuestOrdersList orders={orders} locale="en" />);
  expect(screen.getByText("PUBG Mobile")).toBeInTheDocument();
  const expectedDate = new Intl.DateTimeFormat("en").format(new Date(createdAt));
  expect(screen.getByText(expectedDate)).toBeInTheDocument();
});

it("normalizes (trims + lowercases) the un-normalized stored email in the link", () => {
  const orders: GuestOrder[] = [
    {
      orderId: "o1",
      email: "  Buyer@Example.com  ",
      brandSlug: "pubg",
      brandName: "PUBG Mobile",
      createdAt: "2026-07-01T00:00:00.000Z",
    },
  ];
  wrap(<GuestOrdersList orders={orders} locale="en" />);
  expect(screen.getByRole("link", { name: /PUBG Mobile/ })).toHaveAttribute(
    "href",
    "/en/orders/o1?email=buyer%40example.com",
  );
});
