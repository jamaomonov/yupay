// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { UzqrPaymentDetails } from "@/lib/orders-types";

import { UzqrPayCard } from "./UzqrPayCard";

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

const toDataURL = vi.fn((_text: string, _opts: unknown) =>
  Promise.resolve("data:image/png;base64,QR"),
);
vi.mock("qrcode", () => ({
  toDataURL: (text: string, opts: unknown) => toDataURL(text, opts),
}));

const NOW = 1_700_000_000_000;
const DETAILS: UzqrPaymentDetails = {
  invoice_id: "INV9481964A5BDB4D908A69CE",
  qr_text: "00020101021240440012qr-online.uz",
  amount: "21000.00",
  expires_at: new Date(NOW + 9 * 60_000 + 5_000).toISOString(),
};

describe("UzqrPayCard", () => {
  it("draws the issued QR text, the amount and the time left", async () => {
    render(<UzqrPayCard details={DETAILS} locale="ru" nowMs={NOW} />);

    const img = await screen.findByTestId("uzqr-code");
    expect(img).toHaveAttribute("src", "data:image/png;base64,QR");
    // The text is drawn as issued — never rebuilt from the order.
    expect(toDataURL.mock.calls[0]?.[0]).toBe(DETAILS.qr_text);
    expect(screen.getByText(/21\s?000/)).toBeInTheDocument();
    expect(screen.getByTestId("uzqr-countdown")).toHaveTextContent("09:05");
  });

  it("offers the picture as a PNG to save, for a phone that cannot scan itself", async () => {
    render(<UzqrPayCard details={DETAILS} locale="ru" nowMs={NOW} />);

    const save = await screen.findByRole("link", { name: /uzqrSave/ });
    expect(save).toHaveAttribute("href", "data:image/png;base64,QR");
    expect(save).toHaveAttribute("download", `yupay-qr-${DETAILS.invoice_id}.png`);
  });

  it("says the window closed once the deadline has passed", async () => {
    render(
      <UzqrPayCard
        details={{ ...DETAILS, expires_at: new Date(NOW - 1000).toISOString() }}
        locale="ru"
        nowMs={NOW}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("uzqrExpired");
    await waitFor(() => {
      expect(screen.queryByTestId("uzqr-code")).not.toBeInTheDocument();
    });
  });
});
