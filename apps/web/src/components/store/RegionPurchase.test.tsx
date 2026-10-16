// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { isRegionUnchecked, RegionPurchase, type RegionOption } from "./RegionPurchase";

import type { FormField, ProductDetail } from "@/lib/catalog";

vi.mock("next-intl", () => {
  const known = new Set(["regions.global", "regions.ph"]);
  const t = (k: string, values?: Record<string, string>): string =>
    values ? `${k}:${JSON.stringify(values)}` : k;
  t.has = (k: string): boolean => known.has(k);
  return { useTranslations: () => t };
});

// The panel itself is covered by its own tests; here it only has to show
// which region's products it was handed.
vi.mock("./PurchasePanel", () => ({
  PurchasePanel: ({ products }: { products: ProductDetail[] }) => (
    <ul>
      {products.map((p) => (
        <li key={p.id}>{p.name}</li>
      ))}
    </ul>
  ),
}));

const CHECKED: FormField = {
  key: "player_id",
  label: { ru: "ID" },
  type: "text",
  required: true,
  check: { server_field: null },
};
const UNCHECKED: FormField = { ...CHECKED, check: null };

function product(id: string, name: string, fields: FormField[]): ProductDetail {
  return {
    id,
    slug: id,
    brand_slug: id,
    category_slug: "games",
    name,
    short_description: null,
    image_url: null,
    kind: "top_up",
    starting_price_usd: "1.00",
    starting_display_price: null,
    brand: {
      id,
      slug: id,
      category_slug: "games",
      name,
      short_description: null,
      logo_url: null,
      hero_image_url: null,
      accent_color: null,
      maintenance: false,
    },
    description: null,
    required_fields: fields,
    skus: [],
  };
}

const REGIONS: RegionOption[] = [
  {
    code: "global",
    slug: "mobile-legends",
    products: [product("g", "Global diamonds", [CHECKED])],
  },
  {
    code: "ph",
    slug: "mobile-legends-ph",
    products: [product("p", "PH diamonds", [UNCHECKED])],
  },
  { code: "xx", slug: "mobile-legends-xx", products: [product("x", "XX diamonds", [CHECKED])] },
];

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

it("opens on the main region and switches to another region's products", () => {
  render(<RegionPurchase regions={REGIONS} locale="ru" />);
  expect(screen.getByText("Global diamonds")).toBeInTheDocument();
  expect(screen.queryByText(/regionUnchecked/)).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "regions.ph" }));
  expect(screen.getByText("PH diamonds")).toBeInTheDocument();
  expect(screen.queryByText("Global diamonds")).not.toBeInTheDocument();
  expect(window.location.search).toBe("?region=ph");

  fireEvent.click(screen.getByRole("button", { name: "regions.global" }));
  expect(window.location.search).toBe("");
});

it("preselects the region named in ?region=", () => {
  window.history.replaceState(null, "", "/store/mobile-legends?region=ph");
  render(<RegionPurchase regions={REGIONS} locale="ru" />);
  expect(screen.getByText("PH diamonds")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "regions.ph" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

it("ignores an unknown ?region=", () => {
  window.history.replaceState(null, "", "/store/mobile-legends?region=zz");
  render(<RegionPurchase regions={REGIONS} locale="ru" />);
  expect(screen.getByText("Global diamonds")).toBeInTheDocument();
});

it("warns that a region without a player check is sold unchecked", () => {
  window.history.replaceState(null, "", "/store/mobile-legends?region=ph");
  render(<RegionPurchase regions={REGIONS} locale="ru" />);
  expect(
    screen.getByText(`regionUnchecked:${JSON.stringify({ region: "regions.ph" })}`),
  ).toBeInTheDocument();
});

it("labels a region without a translation by its code", () => {
  render(<RegionPurchase regions={REGIONS} locale="ru" />);
  expect(screen.getByRole("button", { name: "XX" })).toBeInTheDocument();
});

it("isRegionUnchecked: only an id field with no check counts", () => {
  expect(isRegionUnchecked([product("a", "a", [UNCHECKED])])).toBe(true);
  expect(isRegionUnchecked([product("a", "a", [CHECKED])])).toBe(false);
  expect(isRegionUnchecked([product("a", "a", [])])).toBe(false);
});
