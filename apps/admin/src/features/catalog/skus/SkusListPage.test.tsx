// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { SkusListPage } from "./SkusListPage";

import { apiGet } from "@/lib/api";

/**
 * The search lived in component state, so editing a SKU — which navigates away
 * and back — threw it away. An operator working through a filtered list retyped
 * the query after every single edit.
 */

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockedApiGet = vi.mocked(apiGet);

const BRAND = {
  id: "brand-1",
  slug: "roblox",
  category_id: "cat-1",
  logo_url: "https://cdn.example/roblox.png",
  hero_image_url: null,
  accent_color: null,
  sort_order: 0,
  active: true,
  maintenance: false,
  translations: [{ locale: "ru", name: "Roblox" }],
};
const PRODUCT = {
  id: "prod-1",
  slug: "robux",
  brand_id: "brand-1",
  kind: "top_up",
  supplier_hint: null,
  image_url: "https://cdn.example/robux.png",
  sort_order: 0,
  active: true,
  required_fields: [],
  translations: [{ locale: "ru", name: "Robux" }],
};
const SKU = {
  id: "sku-1",
  product_id: "prod-1",
  sku_code: "robux-800",
  denomination: "800 Robux",
  region: "GLOBAL",
  price_usd: "9.99",
  cost_usdt: "8.00",
  rate_multiplier: null,
  min_qty: null,
  max_qty: null,
  image_url: "https://cdn.example/sku.png",
  sort_order: 0,
  active: true,
  price_overrides: [],
};

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/products")) return Promise.resolve([PRODUCT]);
    if (path.includes("/brands")) return Promise.resolve([BRAND]);
    return Promise.resolve([SKU]);
  });
});

/** Renders the page and exposes the current URL, which is where search lives. */
function renderList(initial = "/skus") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let url = "";
  function Spy() {
    const loc = useLocation();
    url = `${loc.pathname}${loc.search}`;
    return null;
  }
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route
            path="/skus"
            element={
              <>
                <SkusListPage />
                <Spy />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { currentUrl: () => url };
}

it("puts the search in the URL, so leaving and coming back keeps it", async () => {
  const { currentUrl } = renderList();
  const field = await screen.findByPlaceholderText(/Поиск по бренду/);

  fireEvent.change(field, { target: { value: "robux" } });

  await waitFor(() => {
    expect(currentUrl()).toContain("q=robux");
  });
});

it("restores the search from the URL on arrival", async () => {
  renderList("/skus?q=robux");
  const field = await screen.findByPlaceholderText(/Поиск по бренду/);
  expect(field).toHaveValue("robux");
});

it("restores the inactive-only filter too", async () => {
  renderList("/skus?inactive=1");
  const box = await screen.findByRole("checkbox");
  expect(box).toBeChecked();
});

it("shows the brand logo and the SKU picture beside their names", async () => {
  renderList();
  await screen.findByText("Robux");
  const sources = Array.from(document.querySelectorAll("img")).map((i) => i.getAttribute("src"));
  // Recognising the artwork is faster than reading the row, which is the whole
  // point — the names stay beside them either way.
  expect(sources).toContain("https://cdn.example/roblox.png");
  expect(sources).toContain("https://cdn.example/sku.png");
});

/**
 * Two defects that made this page unusable on a phone, reported 2026-09-21:
 * "таблица не листается вправо из-за чего нельзя зайти на страницу
 * редактирования".
 *
 * Both are CSS, and jsdom computes no layout — so these assert the classes
 * that carry the behaviour. That is a weaker instrument than a click, and it
 * is the only one that can see a control hidden by `opacity`: the button was
 * always in the DOM, always focusable by testing-library, and invisible to
 * every finger that has ever touched this page.
 */

it("shows the row actions without a hover, because a phone has none", async () => {
  renderList();
  const edit = await screen.findByRole("button", { name: "Редактировать" });
  const actions = edit.parentElement;

  // `opacity-0` only from `md` up. Unconditional, it made the only route to
  // the edit page invisible on touch — and on a keyboard, which is why the
  // focus-within reveal is here too.
  expect(actions?.className).not.toMatch(/(^|\s)opacity-0(\s|$)/);
  expect(actions?.className).toContain("md:opacity-0");
  expect(actions?.className).toContain("md:group-focus-within:opacity-100");
});

it("lets the table be wider than the screen, so it can actually scroll", async () => {
  renderList();
  const table = (await screen.findByRole("table")) as HTMLTableElement;

  // `w-full` alone lets nine columns compress into a phone's width; nothing
  // overflows, so the wrapper's `overflow-x-auto` has nothing to scroll.
  expect(table.className).toMatch(/min-w-\[/);
  expect(table.parentElement?.className).toContain("overflow-x-auto");
});
