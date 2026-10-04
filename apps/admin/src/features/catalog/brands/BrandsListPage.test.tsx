// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { BrandsListPage } from "./BrandsListPage";

import { apiGet } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

function brand(slug: string, retail: boolean, b2b: boolean) {
  return {
    id: slug,
    slug,
    category_id: "c",
    logo_url: null,
    hero_image_url: null,
    accent_color: null,
    sort_order: 0,
    active: true,
    maintenance: false,
    visible_b2b: b2b,
    visible_retail: retail,
    translations: [{ locale: "ru", name: slug }],
  };
}

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <BrandsListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(apiGet).mockResolvedValue([
    brand("pubg-mobile", true, true),
    brand("reseller-only", false, true),
  ]);
});

it("lists every brand with no filter", async () => {
  renderAt("/brands");
  expect(await screen.findByText("reseller-only", { selector: "code" })).toBeInTheDocument();
  expect(screen.getByText("pubg-mobile", { selector: "code" })).toBeInTheDocument();
});

it("applies the storefront filter from the URL", async () => {
  renderAt("/brands?retail=no");
  expect(await screen.findByText("reseller-only", { selector: "code" })).toBeInTheDocument();
  expect(screen.queryByText("pubg-mobile", { selector: "code" })).not.toBeInTheDocument();
  expect(screen.getByText("1 из 2")).toBeInTheDocument();
  expect(screen.getByLabelText("Витрина")).toHaveValue("no");
});
