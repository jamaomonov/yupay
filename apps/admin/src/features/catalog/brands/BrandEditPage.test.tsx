// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { BrandEditPage } from "./BrandEditPage";

import { apiGet } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockedApiGet = vi.mocked(apiGet);

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

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/categories")) return Promise.resolve([CATEGORY]);
    return Promise.resolve([BRAND]);
  });
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
