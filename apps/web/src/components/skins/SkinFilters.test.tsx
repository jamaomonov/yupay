// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, it, vi } from "vitest";

import { SkinFilters } from "./SkinFilters";
import messages from "../../../../../packages/i18n/locales/ru/web.json";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));

it("marks the chosen wear with a ticked box and the rest with empty ones", () => {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      <SkinFilters
        query={{ sort: "-price", exterior: "FN" }}
        facets={{
          categories: [],
          weapons: [],
          exteriors: [{ value: "FN", count: 3 }],
          rarities: [],
        }}
        locale="ru"
      />
    </NextIntlClientProvider>,
  );
  const fn = screen.getByRole("link", { name: /Прямо с завода/ });
  expect(fn).toHaveAttribute("aria-current", "true");
  expect(fn.querySelector("[data-check='on']")).not.toBeNull();
  const mw = screen.getByRole("link", { name: /Немного поношенное/ });
  expect(mw.querySelector("[data-check='off']")).not.toBeNull();
  expect(screen.queryByRole("button", { name: "Применить" })).not.toBeInTheDocument();
});

function renderFilters(category: string | undefined, rarities: string[], exteriors: number) {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      <SkinFilters
        query={{ sort: "-price", ...(category ? { category: category as "agents" } : {}) }}
        facets={{
          categories: [],
          weapons: [],
          exteriors: exteriors ? [{ value: "FN", count: 3 }] : [],
          rarities: rarities.map((value) => ({ value, count: 1, color: null })),
        }}
        locale="ru"
      />
    </NextIntlClientProvider>,
  );
}

it("shows agents only what agents have: their rarities, no wear, no StatTrak", () => {
  renderFilters("agents", ["Master", "Superior"], 0);
  expect(screen.getByRole("link", { name: /Master/ })).toBeInTheDocument();
  expect(screen.queryByText("Качество")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /StatTrak/ })).not.toBeInTheDocument();
});

it("offers the weapon rarity scale when no category is picked", () => {
  renderFilters(undefined, ["Covert", "Master", "Extraordinary", "Mil-Spec Grade"], 5);
  expect(screen.getByRole("link", { name: /Covert/ })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Mil-Spec Grade/ })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Master/ })).not.toBeInTheDocument();
  expect(screen.getByText("Качество")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /StatTrak/ })).toBeInTheDocument();
});
