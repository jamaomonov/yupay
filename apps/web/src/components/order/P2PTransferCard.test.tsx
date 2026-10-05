// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { P2PPaymentDetails } from "@/lib/orders-types";

import { P2PTransferCard } from "./P2PTransferCard";

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

const DETAILS: P2PPaymentDetails = {
  reservation_number: "A1B2C3",
  pan: "9860 3501 4602 3311",
  holder_name: "OMONOV J",
  network: "humo",
  amount_uzs: 21_114,
  expires_at: new Date(1_700_000_000_000 + 9 * 60_000 + 5_000).toISOString(),
};

describe("P2PTransferCard", () => {
  it("shows the card, the holder, the exact amount and the time left", () => {
    render(<P2PTransferCard details={DETAILS} locale="ru" nowMs={1_700_000_000_000} />);

    expect(screen.getByText("9860 3501 4602 3311")).toBeInTheDocument();
    expect(screen.getByText("OMONOV J")).toBeInTheDocument();
    // The reserved amount, which may sit above the order total — never recomputed.
    expect(screen.getByText(/21\s?114/)).toBeInTheDocument();
    expect(screen.getByTestId("p2p-countdown")).toHaveTextContent("09:05");
    expect(screen.getByText("p2pNote")).toBeInTheDocument();
  });

  it("copies the raw card number and the raw amount, without spaces", () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    render(<P2PTransferCard details={DETAILS} locale="ru" nowMs={1_700_000_000_000} />);

    fireEvent.click(screen.getByRole("button", { name: /p2pCopy: p2pCard/ }));
    fireEvent.click(screen.getByRole("button", { name: /p2pCopy: p2pAmount/ }));

    expect(writeText).toHaveBeenNthCalledWith(1, "9860350146023311");
    expect(writeText).toHaveBeenNthCalledWith(2, "21114");
    vi.unstubAllGlobals();
  });

  it("says the window closed once the deadline has passed", () => {
    render(
      <P2PTransferCard
        details={{ ...DETAILS, expires_at: new Date(1_700_000_000_000 - 1000).toISOString() }}
        locale="ru"
        nowMs={1_700_000_000_000}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("p2pExpired");
    expect(screen.queryByText("9860 3501 4602 3311")).not.toBeInTheDocument();
  });
});
