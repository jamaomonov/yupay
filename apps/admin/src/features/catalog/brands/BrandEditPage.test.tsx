// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { BrandEditPage } from "./BrandEditPage";

import { apiGet, apiPatch } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockedApiGet = vi.mocked(apiGet);
const SAVE = "Сохранить";

const CATEGORY = {
  id: "cat-1",
  slug: "games",
  icon: null,
  sort_order: 0,
  active: true,
  translations: [{ locale: "ru", name: "Игры" }],
};

const BRAND = {
  id: "brand-1",
  slug: "roblox",
  category_id: "cat-1",
  logo_url: null,
  hero_image_url: null,
  accent_color: null,
  sort_order: 0,
  active: true,
  maintenance: false,
  visible_b2b: false,
  visible_retail: true,
  translations: [{ locale: "ru", name: "Roblox" }],
};

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/brands/new" element={<BrandEditPage />} />
          <Route path="/brands/:id" element={<BrandEditPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// The categories list feeds the category <select>; the brand itself is one
// row — the page never walks the (326-strong) brands list for it.
function mockCatalog(brand: typeof BRAND = BRAND): void {
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/categories")) return Promise.resolve([CATEGORY]);
    if (path === `/api/v1/admin/catalog/brands/${brand.id}`) return Promise.resolve(brand);
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });
}

beforeEach(() => {
  mockedApiGet.mockReset();
  mockCatalog();
});

it("shows the B2B card with the brand's saved visibility on an existing brand", async () => {
  renderAt("/brands/brand-1");
  expect(await screen.findByLabelText(/Бренд виден мерчантам/)).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Наценка всем SKU бренда" })).toBeInTheDocument();
});

it("hides the B2B card while the brand is not saved yet", async () => {
  renderAt("/brands/new");
  // The form itself is up…
  expect(await screen.findByPlaceholderText("pubg-mobile")).toBeInTheDocument();
  // …but there is no brand row to patch B2B flags onto yet.
  expect(screen.queryByLabelText(/Бренд виден мерчантам/)).not.toBeInTheDocument();
});

it("loads a reseller-only brand with «Показывать клиентам» off and saves the flag", async () => {
  mockCatalog({
    ...BRAND,
    visible_b2b: true,
    visible_retail: false,
    // Every locale named, so the form validates and the save goes out.
    translations: ["ru", "en", "uz"].map((locale) => ({ locale, name: "Roblox" })),
  });
  vi.mocked(apiPatch).mockResolvedValue(BRAND);
  renderAt("/brands/brand-1");

  const box = await screen.findByLabelText(/Показывать клиентам/);
  await waitFor(() => {
    expect(box).not.toBeChecked();
  });
  fireEvent.click(box);
  fireEvent.click(screen.getByRole("button", { name: SAVE }));

  await waitFor(() => {
    expect(apiPatch).toHaveBeenCalled();
  });
  // The mock records the payload as `unknown`; this test only reads one field of it.
  const body = vi.mocked(apiPatch).mock.calls[0]?.[1] as { visible_retail: boolean };
  expect(body.visible_retail).toBe(true);
});

it("says so when the brand does not exist instead of rendering an empty form", async () => {
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/categories")) return Promise.resolve([CATEGORY]);
    // What `api()` throws on a 404 — only `.status` is read by the page.
    return Promise.reject(Object.assign(new Error("404 Not Found"), { status: 404 }));
  });
  renderAt("/brands/brand-gone");
  expect(await screen.findByText("Бренд не найден.")).toBeInTheDocument();
  expect(screen.queryByPlaceholderText("pubg-mobile")).not.toBeInTheDocument();
});

it("shows a new brand to customers by default", async () => {
  renderAt("/brands/new");
  expect(await screen.findByLabelText(/Показывать клиентам/)).toBeChecked();
});
