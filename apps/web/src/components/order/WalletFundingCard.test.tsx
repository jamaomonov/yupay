// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WalletFundingCard } from "./WalletFundingCard";

import type { OrderOut } from "@/lib/orders-types";

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));
vi.mock("./OrderPayNow", () => ({
  OrderPayNow: () => <div data-testid="pay-now" />,
}));

function deposit(status: string): OrderOut {
  // The fields the card reads; the rest of the shape is irrelevant here.
  return {
    id: "01a10fff-8167-70f0-8292-a693081438d2",
    status,
    purpose: "wallet_topup",
    currency: "UZS",
    total_charged: "5000",
    items: [],
  } as unknown as OrderOut; // narrowing a known-shape fixture
}

function renderCard(status: string) {
  const qc = new QueryClient();
  const invalidate = vi.spyOn(qc, "invalidateQueries");
  render(
    <QueryClientProvider client={qc}>
      <WalletFundingCard order={deposit(status)} locale="ru" />
    </QueryClientProvider>,
  );
  return { invalidate };
}

describe("WalletFundingCard", () => {
  it("says the balance is topped up and refreshes the wallet once delivered", () => {
    const { invalidate } = renderCard("delivered");

    expect(screen.getByTestId("wallet-funding")).toHaveAttribute("data-phase", "credited");
    expect(screen.getByText("walletTopUp.credited.title")).toBeInTheDocument();
    expect(screen.getByText(/5\s?000/)).toBeInTheDocument();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["wallet"] });
    expect(screen.queryByTestId("pay-now")).not.toBeInTheDocument();
  });

  it("offers the way to pay while the deposit is waiting, and does not touch the wallet", () => {
    const { invalidate } = renderCard("pending_payment");

    expect(screen.getByTestId("wallet-funding")).toHaveAttribute("data-phase", "waiting");
    expect(screen.getByTestId("pay-now")).toBeInTheDocument();
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("shows crediting between paid and delivered", () => {
    renderCard("paid");
    expect(screen.getByTestId("wallet-funding")).toHaveAttribute("data-phase", "crediting");
    expect(screen.queryByTestId("pay-now")).not.toBeInTheDocument();
  });

  it("offers a retry on a failed deposit", () => {
    renderCard("expired");

    expect(screen.getByTestId("wallet-funding")).toHaveAttribute("data-phase", "failed");
    expect(screen.getByRole("link", { name: "walletTopUp.retry" })).toHaveAttribute(
      "href",
      expect.stringContaining("/account/wallet/top-up"),
    );
  });
});
