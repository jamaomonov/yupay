// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ProductEditPage } from "./ProductEditPage";

import type { Brand, Product } from "../types";

import { apiGet, apiPatch } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockedApiGet = vi.mocked(apiGet);
const mockedApiPatch = vi.mocked(apiPatch);

const BRAND: Brand = {
  id: "brand-1",
  slug: "mobile-legends",
  category_id: "cat-1",
  logo_url: null,
  hero_image_url: null,
  accent_color: null,
  sort_order: 0,
  active: true,
  maintenance: false,
  visible_b2b: false,
  translations: [{ locale: "ru", name: "Mobile Legends" }],
};

// The exact shape that used to get silently stripped: a live G2B check on
// player_id, with a sibling server field named via server_field.
const PRODUCT: Product = {
  id: "prod-1",
  slug: "mlbb-diamonds",
  brand_id: "brand-1",
  kind: "top_up",
  supplier_hint: null,
  image_url: null,
  sort_order: 0,
  active: true,
  required_fields: [
    {
      key: "player_id",
      label: { ru: "ID игрока" },
      type: "text",
      required: true,
      pattern: "^[0-9]{5,20}$",
      check: { provider: "g2b", server_field: "server" },
    },
    {
      key: "server",
      label: { ru: "ID сервера" },
      type: "text",
      required: true,
      pattern: "^[0-9]{3,6}$",
    },
  ],
  // The reset effect always builds one entry per locale — an empty name on
  // en/uz would fail translationSchema's min(1) and silently block submit.
  translations: [
    { locale: "ru", name: "Алмазы", short_description: null, description: null },
    { locale: "en", name: "Diamonds", short_description: null, description: null },
    { locale: "uz", name: "Olmoslar", short_description: null, description: null },
  ],
};

function mockCatalog(): void {
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/brands")) return Promise.resolve([BRAND]);
    if (path.includes("/products")) return Promise.resolve([PRODUCT]);
    return Promise.resolve([]);
  });
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/products/prod-1"]}>
        <Routes>
          <Route path="/products/:id" element={<ProductEditPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiPatch.mockReset();
  mockedApiPatch.mockResolvedValue(PRODUCT);
  mockCatalog();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("keeps a field's G2B check intact when the product is saved untouched", async () => {
  renderPage();

  // The Save button renders unconditionally, before the fetched product's
  // data has landed in the form (`form.reset` only fires once both queries
  // resolve) — wait for something reset-dependent first, or this races and
  // submits the EMPTY defaults instead of the real product.
  await screen.findByText("player_id");
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

  await waitFor(() => {
    expect(mockedApiPatch).toHaveBeenCalledTimes(1);
  });

  const [, body] = mockedApiPatch.mock.calls[0] as [string, { required_fields: unknown[] }];
  expect(body.required_fields[0]).toMatchObject({
    key: "player_id",
    check: { provider: "g2b", server_field: "server" },
  });
});

it("surfaces a help_images cap violation near Save instead of silently doing nothing", async () => {
  // Before this fix, a `required_fields.N.help_images` zod error (max 6,
  // e.g. a malformed payload or a client-side race past the cap in
  // HelpImagesEditor) failed validation silently: `handleSubmit`'s success
  // callback never fires, `Field`'s `error` prop only ever covered slug/
  // brand_id, and Save just did nothing with no explanation on screen.
  const sevenImages = Array.from({ length: 7 }, (_, i) => ({
    url: `https://cdn.yupay.uz/field-help/${String(i)}.png`,
    caption: { ru: "", en: "", uz: "" },
  }));
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/brands")) return Promise.resolve([BRAND]);
    if (path.includes("/products")) {
      return Promise.resolve([
        {
          ...PRODUCT,
          required_fields: [{ ...PRODUCT.required_fields[0]!, help_images: sevenImages }],
        },
      ]);
    }
    return Promise.resolve([]);
  });

  renderPage();

  await screen.findByText("player_id");
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

  expect(await screen.findByText(/Поле формы №1 «Где найти\?»/)).toBeInTheDocument();
  expect(mockedApiPatch).not.toHaveBeenCalled();
});

it("shows the G2B check as enabled and lets it be turned off", async () => {
  renderPage();

  // Each field row starts collapsed — expand player_id to reach its checkbox.
  fireEvent.click(await screen.findByText("player_id"));
  const checkbox = await screen.findByRole("checkbox", {
    name: /Живая проверка ID через G2B/i,
  });
  expect(checkbox).toBeChecked();

  fireEvent.click(checkbox);
  expect(checkbox).not.toBeChecked();
  fireEvent.click(await screen.findByRole("button", { name: "Сохранить" }));

  await waitFor(() => {
    expect(mockedApiPatch).toHaveBeenCalledTimes(1);
  });
  const [, body] = mockedApiPatch.mock.calls[0] as [string, { required_fields: unknown[] }];
  expect(body.required_fields[0]).toMatchObject({ key: "player_id", check: null });
});
