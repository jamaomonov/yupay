// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { SkusListPage } from "./SkusListPage";

import { apiGet } from "@/lib/api";

/**
 * The list is server-paged since the catalogue passed 6000 SKUs: every filter
 * lives in the URL (so editing a SKU — which navigates away and back — keeps
 * it, and a filtered list is a link you can send), and the request carries
 * the filters as query params instead of the page filtering a full download.
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
const OTHER_BRAND = { ...BRAND, id: "brand-2", slug: "steam", translations: [] };
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
/** Same brand, no SKU behind it. */
const EMPTY_PRODUCT = {
  ...PRODUCT,
  id: "prod-2",
  slug: "robux-gift-card",
  translations: [{ locale: "ru", name: "Robux Gift Card" }],
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

let skuPage: { items: (typeof SKU)[]; total: number } = { items: [SKU], total: 1 };

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  skuPage = { items: [SKU], total: 1 };
  mockedApiGet.mockReset();
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/products")) return Promise.resolve([PRODUCT, EMPTY_PRODUCT]);
    if (path.includes("/brands")) return Promise.resolve([BRAND, OTHER_BRAND]);
    return Promise.resolve(skuPage);
  });
});

afterEach(() => {
  vi.useRealTimers();
});

/** The query string of the most recent SKU-page request. */
function lastSkuRequest(): URLSearchParams {
  const paths = mockedApiGet.mock.calls
    .map((c) => c[0])
    .filter((p) => p.startsWith("/api/v1/admin/catalog/skus?"));
  const last = paths.at(-1);
  if (!last) throw new Error("no /skus request yet");
  return new URLSearchParams(last.slice(last.indexOf("?") + 1));
}

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

/** A product group's heading — by role, because the product `<select>` has an
 *  `<option>` with the same text and `findByText` would see both. */
const findGroup = (name: string) => screen.findByRole("heading", { name });
const queryGroup = (name: string) => screen.queryByRole("heading", { name });

async function settleDebounce() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
}

it("asks the server for one page, not the whole catalogue", async () => {
  renderList();
  await findGroup("Robux");
  const sp = lastSkuRequest();
  expect(sp.get("limit")).toBe("100");
  expect(sp.get("offset")).toBe("0");
  expect(sp.has("q")).toBe(false);
  expect(sp.has("active")).toBe(false);
});

it("puts the search in the URL after the debounce, and sends it to the server", async () => {
  const { currentUrl } = renderList();
  const field = await screen.findByPlaceholderText(/Поиск по бренду/);

  fireEvent.change(field, { target: { value: "robux" } });
  // Typed, but not yet a request: the URL still has no `q`.
  expect(currentUrl()).toBe("/skus");

  await settleDebounce();

  await waitFor(() => {
    expect(currentUrl()).toContain("q=robux");
  });
  await waitFor(() => {
    expect(lastSkuRequest().get("q")).toBe("robux");
  });
});

it("restores the search from the URL on arrival and requests with it", async () => {
  renderList("/skus?q=robux");
  const field = await screen.findByPlaceholderText(/Поиск по бренду/);
  expect(field).toHaveValue("robux");
  await waitFor(() => {
    expect(lastSkuRequest().get("q")).toBe("robux");
  });
});

it("restores the inactive-only filter too, as active=false on the wire", async () => {
  renderList("/skus?inactive=1");
  const box = await screen.findByRole("checkbox");
  expect(box).toBeChecked();
  await waitFor(() => {
    expect(lastSkuRequest().get("active")).toBe("false");
  });
});

it("sends the brand and product filters as ids", async () => {
  renderList("/skus?brand=brand-1&product=prod-1");
  await waitFor(() => {
    const sp = lastSkuRequest();
    expect(sp.get("brand_id")).toBe("brand-1");
    expect(sp.get("product_id")).toBe("prod-1");
  });
  expect(await screen.findByRole("combobox", { name: "Бренд" })).toHaveValue("brand-1");
  expect(screen.getByRole("combobox", { name: "Продукт" })).toHaveValue("prod-1");
});

it("walks pages through the URL offset", async () => {
  skuPage = { items: [SKU], total: 250 };
  const { currentUrl } = renderList("/skus?offset=100");

  expect(await screen.findByText("101–200 из 250")).toBeInTheDocument();
  expect(lastSkuRequest().get("offset")).toBe("100");

  fireEvent.click(screen.getByRole("button", { name: "Следующая страница" }));
  await waitFor(() => {
    expect(currentUrl()).toContain("offset=200");
  });
  await waitFor(() => {
    expect(lastSkuRequest().get("offset")).toBe("200");
  });
});

it("goes back to the first page when a filter changes", async () => {
  skuPage = { items: [SKU], total: 250 };
  const { currentUrl } = renderList("/skus?offset=100");
  const box = await screen.findByRole("checkbox");

  fireEvent.click(box);

  await waitFor(() => {
    expect(currentUrl()).toContain("inactive=1");
  });
  expect(currentUrl()).not.toContain("offset");
});

it("drops the product filter when the brand changes, since it was scoped to the old one", async () => {
  const { currentUrl } = renderList("/skus?brand=brand-1&product=prod-1&offset=100");
  const brand = await screen.findByRole("combobox", { name: "Бренд" });

  fireEvent.change(brand, { target: { value: "brand-2" } });

  await waitFor(() => {
    expect(currentUrl()).toContain("brand=brand-2");
  });
  expect(currentUrl()).not.toContain("product=");
  expect(currentUrl()).not.toContain("offset=");
});

it("shows the found total from the server, not the page length", async () => {
  skuPage = { items: [SKU], total: 6150 };
  renderList();
  await findGroup("Robux");
  const card = screen.getByText("Найдено SKU").parentElement;
  expect(card?.textContent).toContain("6150");
});

it("surfaces a brand's SKU-less products only when the brand is filtered", async () => {
  renderList("/skus?brand=brand-1");
  expect(await findGroup("Robux Gift Card")).toBeInTheDocument();
  expect(screen.getByText(/Ни одного SKU/)).toBeInTheDocument();
});

it("cannot know which products are empty from one page of many, so says nothing", async () => {
  renderList();
  await findGroup("Robux");
  expect(queryGroup("Robux Gift Card")).not.toBeInTheDocument();
  expect(screen.queryByText(/Ни одного SKU/)).not.toBeInTheDocument();
});

it("shows the brand logo and the SKU picture beside their names", async () => {
  renderList();
  await findGroup("Robux");
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
