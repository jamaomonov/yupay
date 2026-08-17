import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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
  expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
});
