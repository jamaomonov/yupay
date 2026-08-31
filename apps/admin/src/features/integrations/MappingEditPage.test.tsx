import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { MappingEditPage } from "./MappingEditPage";

import { api, apiGet } from "@/lib/api";

/**
 * This form was hardcoded to G2B — `supplier_slug: "g2b"` on save, and a
 * product picker reading only G2B's cached catalogue. So a supplier could be
 * fully integrated on the backend and still be unusable, because the mapping
 * row it needs could not be created anywhere. G-Engine was exactly that: its
 * fulfiller refuses with "no active g-engine mapping for this SKU", and no
 * screen could produce one.
 */

vi.mock("@/lib/api", () => ({
  api: vi.fn(),
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));

const mockedApiGet = vi.mocked(apiGet);
const mockedApi = vi.mocked(api);

const SKU = {
  id: "sku-1",
  code: "MLBB-100",
  title: "Mobile Legends 100 алмазов",
  product_kind: "top_up",
  product_title: "Mobile Legends",
  denomination: "100",
};

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApi.mockReset();
  mockedApi.mockResolvedValue({ created: true });
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/catalog/skus/search")) return Promise.resolve([SKU]);
    // G-Engine has no catalogue rows — that is the whole reason the manual
    // field exists — and G2B's catalogue is irrelevant to these assertions.
    return Promise.resolve({ items: [] });
  });
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <MappingEditPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Steps 1–2 are untouched by this change; get past them to reach step 3. */
async function reachSupplierStep() {
  fireEvent.click(screen.getByRole("combobox", { name: "SKU" }));
  // Scoped to the listbox: the supplier `<select>` further down the page also
  // publishes `option` roles.
  const list = await screen.findByRole("listbox");
  fireEvent.click(await within(list).findByRole("option"));
  fireEvent.click(screen.getByText("Игровой топ-ап"));
  return screen.getByLabelText("Поставщик");
}

it("offers the suppliers that actually consume a mapping", async () => {
  renderPage();
  const picker = await reachSupplierStep();

  expect(picker).toHaveValue("g2b");
  const slugs = [...picker.querySelectorAll("option")].map((o) => o.getAttribute("value"));

  expect(slugs).toContain("gengine");
  // Waxpeer derives a Steam top-up from the order itself and needs no mapping
  // row; listing it would offer to save a row nothing ever reads.
  expect(slugs).not.toContain("waxpeer");
  expect(slugs).not.toContain("inventory");
});

it("lets the ids be typed in for a supplier whose catalogue we do not mirror", async () => {
  renderPage();
  const picker = await reachSupplierStep();

  fireEvent.change(picker, { target: { value: "gengine" } });

  // The combobox would show an empty list forever, so it is replaced rather
  // than left there looking broken.
  expect(screen.queryByRole("combobox", { name: /Выберите игру/ })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("ID сервиса у поставщика"), { target: { value: "5" } });
  fireEvent.change(screen.getByLabelText("ID номинала у поставщика"), { target: { value: "1" } });

  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

  await waitFor(() => {
    expect(mockedApi).toHaveBeenCalled();
  });
  // `api` is called with a JSON string body; narrowing it back for the
  // assertion, since RequestInit types it as the wider BodyInit.
  const raw = mockedApi.mock.calls[0]?.[1]?.body as string | undefined;
  const body: unknown = JSON.parse(raw ?? "{}");
  expect(body).toMatchObject({
    supplier_slug: "gengine",
    external_product_id: "5",
    external_variant_id: "1",
  });
});

it("can save an amount-priced service that has no denomination", async () => {
  // Telegram Stars: G-Engine's service 72 has no denominations at all, and the
  // star count rides on the quantity. Requiring a denomination here would block
  // by hand exactly what the seed creates in bulk.
  renderPage();
  const picker = await reachSupplierStep();

  fireEvent.change(picker, { target: { value: "gengine" } });
  fireEvent.change(screen.getByLabelText("ID сервиса у поставщика"), { target: { value: "72" } });
  // Not "Множитель" here: for an amount-priced service the field is the amount
  // itself, and calling it a multiplier would mislead whoever fills it in.
  fireEvent.change(screen.getByLabelText("Количество"), { target: { value: "250" } });

  const save = screen.getByRole("button", { name: "Сохранить" });
  expect(save).toBeEnabled();
  fireEvent.click(save);

  await waitFor(() => {
    expect(mockedApi).toHaveBeenCalled();
  });
  const raw = mockedApi.mock.calls[0]?.[1]?.body as string | undefined;
  const body: unknown = JSON.parse(raw ?? "{}");
  expect(body).toMatchObject({
    supplier_slug: "gengine",
    external_product_id: "72",
    external_variant_id: null,
    quantity: 250,
  });
});

it("drops the ids when the supplier changes", async () => {
  // Ids are per-supplier. Carrying one over would point G-Engine at a product
  // id that means something else in their catalogue — and it would save
  // without complaint.
  renderPage();
  const picker = await reachSupplierStep();

  fireEvent.change(picker, { target: { value: "gengine" } });
  fireEvent.change(screen.getByLabelText("ID сервиса у поставщика"), { target: { value: "5" } });
  fireEvent.change(picker, { target: { value: "g2b" } });
  fireEvent.change(picker, { target: { value: "gengine" } });

  expect(screen.getByLabelText("ID сервиса у поставщика")).toHaveValue("");
  // Disabled because the product id is gone — the denomination is optional for
  // this supplier, so it is not what is blocking here.
  expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
});

it("prefills an edited SKU by id, not by hoping it fits the first search page", async () => {
  // Prod had 183 SKUs; the edited one sat at position 130 of a 30-row default
  // page, the prefill silently missed, and «Сохранить» stayed disabled no
  // matter what the admin changed. The prefill must ask for the exact id.
  const SKU_130 = { ...SKU, id: "sku-130" };
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/catalog/skus/search")) {
      return Promise.resolve(path.includes("sku_id=sku-130") ? [SKU_130] : []);
    }
    if (path.includes("/admin/integrations/mappings")) {
      return Promise.resolve({
        items: [
          {
            sku_id: "sku-130",
            supplier_slug: "g2b",
            kind: "game",
            quantity: 1,
            is_active: true,
            external_product_id: "pubg-mobile",
            external_variant_id: "1800",
            extra: {},
          },
        ],
      });
    }
    return Promise.resolve({ items: [] });
  });

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/integrations/mappings/g2b/sku-130/edit"]}>
        <Routes>
          <Route path="/integrations/mappings/:supplier/:sku/edit" element={<MappingEditPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );

  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeEnabled();
  });
});
