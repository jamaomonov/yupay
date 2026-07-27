// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { SteamZeroCommission } from "./SteamZeroCommission";

vi.mock("next-intl/server", () => ({
  getTranslations: async () => (k: string) => `steamZero.${k}`,
}));

test("renders heading, CTA to /store/steam and payment icons", async () => {
  render(await SteamZeroCommission({ locale: "ru" }));
  expect(screen.getByRole("heading", { name: /steamZero\.title/ })).toBeInTheDocument();
  const cta = screen.getByRole("link", { name: /steamZero\.cta/ });
  expect(cta).toHaveAttribute("href", "/ru/store/steam");
  for (const p of ["Uzcard", "Humo", "Click", "Payme", "Uzum"]) {
    expect(screen.getByAltText(p)).toBeInTheDocument();
  }
  expect(screen.queryByAltText("USDT")).not.toBeInTheDocument();
});
