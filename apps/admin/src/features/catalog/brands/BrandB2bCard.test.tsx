// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { BrandB2bCard } from "./BrandB2bCard";

import type { Brand } from "../types";

import { apiPatch, apiPost } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiPatch: vi.fn(),
  apiPost: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockedApiPatch = vi.mocked(apiPatch);
const mockedApiPost = vi.mocked(apiPost);

const BRAND: Brand = {
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

function renderCard(brand: Brand = BRAND) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <BrandB2bCard brand={brand} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiPatch.mockReset();
  mockedApiPost.mockReset();
});

it("flips brand-level B2B visibility through the dedicated endpoint", async () => {
  mockedApiPatch.mockResolvedValue({ id: "brand-1", slug: "roblox", visible_b2b: true });
  renderCard();

  const toggle = screen.getByLabelText(/Бренд виден мерчантам/);
  expect(toggle).not.toBeChecked();
  fireEvent.click(toggle);

  await waitFor(() => {
    expect(mockedApiPatch).toHaveBeenCalledTimes(1);
  });
  const [url, body, headers] = mockedApiPatch.mock.calls[0] ?? [];
  expect(url).toBe("/api/v1/admin/catalog/brands/brand-1/b2b");
  expect(body).toEqual({ visible_b2b: true });
  expect(headers).toEqual(
    expect.objectContaining({ "Idempotency-Key": expect.any(String) as string }),
  );
});

it("bulk markup asks for confirmation first, then posts and reports the affected count", async () => {
  mockedApiPost.mockResolvedValue({ affected: 12 });
  renderCard();

  fireEvent.change(screen.getByLabelText("Наценка, %"), { target: { value: "5" } });
  fireEvent.click(screen.getByRole("button", { name: "Наценка всем SKU бренда" }));

  // Nothing fired yet — the dialog naming the brand and the markup is up first:
  // this action rewrites the markup of every SKU of the brand.
  expect(mockedApiPost).not.toHaveBeenCalled();
  expect(screen.getByText(/«Roblox» будет установлена наценка B2B 5%/)).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Да, применить" }));
  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledTimes(1);
  });
  const [url, body, headers] = mockedApiPost.mock.calls[0] ?? [];
  expect(url).toBe("/api/v1/admin/catalog/b2b/bulk-markup");
  expect(body).toEqual({ brand_slug: "roblox", markup_pct: "5" });
  expect(headers).toEqual(
    expect.objectContaining({ "Idempotency-Key": expect.any(String) as string }),
  );

  expect(await screen.findByText("Обновлено SKU: 12.")).toBeInTheDocument();
});

it("cancelling the confirmation fires nothing", async () => {
  renderCard();
  fireEvent.change(screen.getByLabelText("Наценка, %"), { target: { value: "5" } });
  fireEvent.click(screen.getByRole("button", { name: "Наценка всем SKU бренда" }));
  fireEvent.click(await screen.findByRole("button", { name: "Отмена" }));
  expect(mockedApiPost).not.toHaveBeenCalled();
  expect(screen.queryByText(/будет установлена наценка/)).not.toBeInTheDocument();
});

it("does not open the confirmation for a markup the column cannot hold", () => {
  renderCard();
  fireEvent.change(screen.getByLabelText("Наценка, %"), { target: { value: "12.345" } });
  fireEvent.click(screen.getByRole("button", { name: "Наценка всем SKU бренда" }));
  expect(screen.queryByText(/будет установлена наценка/)).not.toBeInTheDocument();
  expect(
    screen.getByText("Наценка — число до ±999.99, максимум два знака после точки."),
  ).toBeInTheDocument();
});
