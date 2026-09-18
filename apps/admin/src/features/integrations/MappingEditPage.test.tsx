import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { MappingEditPage } from "./MappingEditPage";

import { api, apiGet, apiPost } from "@/lib/api";

/**
 * This form was hardcoded to G2B — `supplier_slug: "g2b"` on save, and a
 * product picker reading only G2B's cached catalogue. So a supplier could be
 * fully integrated on the backend and still be unusable, because the mapping
 * row it needs could not be created anywhere. G-Engine was exactly that: its
 * fulfiller refuses with "no active g-engine mapping for this SKU", and no
 * screen could produce one.
 *
 * The pickers are now generalised over every `MAPPING_REQUIRED_SUPPLIERS`
 * slug (g2b, gengine, nova) instead of just G2B — the operator no longer has
 * to know a supplier's raw id to map a SKU to it, only to search its cached
 * title. Manual id entry stays available underneath, collapsed, for when the
 * cache hasn't caught up with the supplier yet.
 */

vi.mock("@/lib/api", () => ({
  api: vi.fn(),
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  ApiError: class ApiError extends Error {},
  formatApiError: (err: unknown) => (err instanceof Error ? err.message : "error"),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));

const mockedApiGet = vi.mocked(apiGet);
const mockedApiPost = vi.mocked(apiPost);
const mockedApi = vi.mocked(api);

const SKU = {
  id: "sku-1",
  code: "MLBB-100",
  title: "Mobile Legends 100 алмазов",
  product_kind: "top_up",
  product_title: "Mobile Legends",
  denomination: "100",
};

// G-Engine, not G2B: `DenomCatalogPicker` (the cache-backed picker these
// fixtures exercise) only ever renders for NOVA/G-Engine — G2B's own live
// picker (`DenomPicker`) is untouched by this change and isn't exercised
// here. See `DenomCatalogPicker.tsx`'s module docstring for why.
const GAME_MLBB = {
  supplier_slug: "gengine",
  kind: "game",
  external_id: "mlbb",
  title: "Mobile Legends",
  raw: {},
  fetched_at: "2026-01-01T00:00:00Z",
  parent_external_id: null,
  price_usdt: null,
};

const GAME_PUBG = {
  ...GAME_MLBB,
  external_id: "pubg",
  title: "PUBG Mobile",
};

const DENOM_MLBB_100 = {
  supplier_slug: "gengine",
  kind: "game_denom",
  external_id: "100-diamonds",
  title: "100 Diamonds",
  raw: {},
  fetched_at: "2026-01-01T00:00:00Z",
  parent_external_id: "mlbb",
  price_usdt: "1.50",
};

const DENOM_PUBG_60 = {
  ...DENOM_MLBB_100,
  external_id: "60-uc",
  title: "60 UC",
  parent_external_id: "pubg",
  price_usdt: "0.90",
};

/** Routes `/admin/integrations/catalog` requests to a `kind`-keyed table,
 *  the way the real endpoint would filter by `kind` (+ `parent_external_id`
 *  for `game_denom`). Keeps each test's mock declarative instead of a chain
 *  of `path.includes(...)` checks that are easy to get subtly wrong — e.g.
 *  `"kind=game_denom".includes("kind=game")` is true, so ordering matters
 *  and a URL parse sidesteps it entirely. */
function mockCatalogEndpoint(byKind: { game?: unknown[]; game_denom?: Record<string, unknown[]> }) {
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/catalog/skus/search")) return Promise.resolve([SKU]);
    if (path.includes("/admin/integrations/catalog")) {
      const url = new URL(path, "http://test.local");
      const kind = url.searchParams.get("kind");
      if (kind === "game") return Promise.resolve({ items: byKind.game ?? [] });
      if (kind === "game_denom") {
        const parent = url.searchParams.get("parent_external_id") ?? "";
        return Promise.resolve({ items: byKind.game_denom?.[parent] ?? [] });
      }
    }
    return Promise.resolve({ items: [] });
  });
}

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiPost.mockReset();
  mockedApi.mockReset();
  mockedApi.mockResolvedValue({ created: true });
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/catalog/skus/search")) return Promise.resolve([SKU]);
    // Empty cache by default — the whole point of most of these assertions
    // is what the UI offers when a supplier's cache has nothing yet.
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

/** Opens a Combobox by its accessible name and clicks the named option. */
async function pickFromCombobox(triggerName: string, optionName: RegExp) {
  fireEvent.click(screen.getByRole("combobox", { name: triggerName }));
  const list = await screen.findByRole("listbox");
  fireEvent.click(await within(list).findByRole("option", { name: optionName }));
}

it("offers the suppliers that actually consume a mapping", async () => {
  renderPage();
  const picker = await reachSupplierStep();

  expect(picker).toHaveValue("g2b");
  const slugs = [...picker.querySelectorAll("option")].map((o) => o.getAttribute("value"));

  expect(slugs).toContain("gengine");
  // NOVA is a reserve supplier — an operator hand-switches a SKU to it via
  // `force_supplier` — but it still consumes a mapping row like G-Engine.
  expect(slugs).toContain("nova");
  // Waxpeer derives a Steam top-up from the order itself and needs no mapping
  // row; listing it would offer to save a row nothing ever reads.
  expect(slugs).not.toContain("waxpeer");
  expect(slugs).not.toContain("inventory");
});

it("fills the submitted body by picking a game, then a denomination scoped to it", async () => {
  mockCatalogEndpoint({
    game: [GAME_MLBB, GAME_PUBG],
    game_denom: { mlbb: [DENOM_MLBB_100], pubg: [DENOM_PUBG_60] },
  });
  renderPage();
  const picker = await reachSupplierStep(); // leaves kind=game
  // `DenomCatalogPicker` (the cache-backed denomination picker) only renders
  // for NOVA/G-Engine — G2B keeps its own live picker, untouched here.
  fireEvent.change(picker, { target: { value: "gengine" } });

  await pickFromCombobox("Игра у поставщика", /Mobile Legends/);
  await pickFromCombobox("Номинал", /100 Diamonds/);

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
    external_product_id: "mlbb",
    external_variant_id: "100-diamonds",
  });
});

it("scopes the denomination picker to the chosen game", async () => {
  mockCatalogEndpoint({
    game: [GAME_MLBB, GAME_PUBG],
    game_denom: { mlbb: [DENOM_MLBB_100], pubg: [DENOM_PUBG_60] },
  });
  renderPage();
  const picker = await reachSupplierStep();
  fireEvent.change(picker, { target: { value: "gengine" } });

  await pickFromCombobox("Игра у поставщика", /Mobile Legends/);
  fireEvent.click(screen.getByRole("combobox", { name: "Номинал" }));
  const mlbbList = await screen.findByRole("listbox");
  expect(within(mlbbList).getByRole("option", { name: /100 Diamonds/ })).toBeInTheDocument();
  expect(within(mlbbList).queryByRole("option", { name: /60 UC/ })).not.toBeInTheDocument();
  // Close it (no selection) before switching games — `fireEvent.click` does not
  // synthesise the mousedown an outside click relies on to auto-close.
  fireEvent.click(screen.getByRole("combobox", { name: "Номинал" }));

  // Picking a different game re-queries the denomination cache with the new
  // parent — the previous game's denominations must not leak into the list.
  await pickFromCombobox("Игра у поставщика", /PUBG Mobile/);
  fireEvent.click(screen.getByRole("combobox", { name: "Номинал" }));
  const pubgList = await screen.findByRole("listbox");
  expect(within(pubgList).getByRole("option", { name: /60 UC/ })).toBeInTheDocument();
  expect(within(pubgList).queryByRole("option", { name: /100 Diamonds/ })).not.toBeInTheDocument();
});

it("offers a pull-denominations button when the cache has none for the chosen game, and shows what it returns", async () => {
  let pulled = false;
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/catalog/skus/search")) return Promise.resolve([SKU]);
    if (path.includes("/admin/integrations/catalog")) {
      const url = new URL(path, "http://test.local");
      const kind = url.searchParams.get("kind");
      if (kind === "game") return Promise.resolve({ items: [GAME_MLBB] });
      if (kind === "game_denom") {
        return Promise.resolve({ items: pulled ? [DENOM_MLBB_100] : [] });
      }
    }
    return Promise.resolve({ items: [] });
  });
  mockedApiPost.mockImplementation((path: string) => {
    if (path.includes("/sync-denominations")) {
      pulled = true;
      return Promise.resolve({
        supplier: "gengine",
        game_id: "mlbb",
        denominations_synced: 1,
        error: null,
      });
    }
    return Promise.resolve({});
  });

  renderPage();
  const picker = await reachSupplierStep();
  fireEvent.change(picker, { target: { value: "gengine" } });
  await pickFromCombobox("Игра у поставщика", /Mobile Legends/);

  expect(await screen.findByText(/В кэше нет номиналов для этой игры/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Подтянуть номиналы у поставщика" }));

  // An Idempotency-Key rides every attempt, minted fresh — not reused.
  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledWith(
      expect.stringContaining("/admin/integrations/gengine/games/mlbb/sync-denominations"),
      {},
      expect.objectContaining({ "Idempotency-Key": expect.any(String) as string }),
    );
  });

  // ...and then shows what came back, instead of leaving the empty list.
  fireEvent.click(await screen.findByRole("combobox", { name: "Номинал" }));
  const list = await screen.findByRole("listbox");
  expect(within(list).getByRole("option", { name: /100 Diamonds/ })).toBeInTheDocument();
});

it("shows the backend's in-band sync error instead of the generic no-denominations line", async () => {
  // `POST .../sync-denominations` reports failure in-band on a 200
  // (`DenomSyncOut.error`), not as a transport error — e.g. "g-engine has no
  // recharge service 999" or "NOVA_API_KEY is not configured" — so
  // `sync.isError` alone never sees it, and the picker used to fall back to
  // the generic "поставщик не вернул ни одного номинала" line, discarding the
  // specific, actionable reason.
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/catalog/skus/search")) return Promise.resolve([SKU]);
    if (path.includes("/admin/integrations/catalog")) {
      const url = new URL(path, "http://test.local");
      const kind = url.searchParams.get("kind");
      if (kind === "game") return Promise.resolve({ items: [GAME_MLBB] });
      if (kind === "game_denom") return Promise.resolve({ items: [] });
    }
    return Promise.resolve({ items: [] });
  });
  mockedApiPost.mockImplementation((path: string) => {
    if (path.includes("/sync-denominations")) {
      return Promise.resolve({
        supplier: "gengine",
        game_id: "mlbb",
        denominations_synced: 0,
        error: "g-engine has no recharge service 999",
      });
    }
    return Promise.resolve({});
  });

  renderPage();
  const picker = await reachSupplierStep();
  fireEvent.change(picker, { target: { value: "gengine" } });
  await pickFromCombobox("Игра у поставщика", /Mobile Legends/);

  // Wait for the cache-empty state to actually render before clicking —
  // `pickFromCombobox` only waits for the game combobox, not the
  // denomination cache query it triggers.
  expect(await screen.findByText(/В кэше нет номиналов для этой игры/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Подтянуть номиналы у поставщика" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "g-engine has no recharge service 999",
  );
  expect(screen.queryByText(/не вернул ни одного номинала/)).not.toBeInTheDocument();
});

it("lets an id be typed in through the manual fallback when the cache has nothing for the supplier", async () => {
  renderPage();
  const picker = await reachSupplierStep();

  fireEvent.change(picker, { target: { value: "gengine" } });

  // The picker is still offered even though the mocked cache is empty for
  // it — only the manual path used to disappear here, and it must not.
  expect(screen.getByRole("combobox", { name: "Игра у поставщика" })).toBeInTheDocument();

  fireEvent.click(screen.getByText("Ввести ID вручную — если поставщик ещё не в кэше"));
  fireEvent.change(screen.getByLabelText("ID сервиса у поставщика"), { target: { value: "5" } });
  fireEvent.click(screen.getByText("Ввести ID номинала вручную — если поставщик ещё не в кэше"));
  fireEvent.change(screen.getByLabelText("ID номинала у поставщика"), { target: { value: "1" } });

  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

  await waitFor(() => {
    expect(mockedApi).toHaveBeenCalled();
  });
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
  fireEvent.click(screen.getByText("Ввести ID вручную — если поставщик ещё не в кэше"));
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

it("saves NOVA's Steam mapping with no denomination, but still demands one for a game", async () => {
  // Their Steam endpoint takes a login and an amount — no category, no
  // denomination — so the mapping that reaches it carries a sentinel product
  // id and nothing in the номинал field. This gate is a mirror of the API's
  // own; when the two disagreed, Save stayed disabled on a mapping the API
  // would have accepted and the Steam reserve could not be created at all.
  renderPage();
  const picker = await reachSupplierStep();

  fireEvent.change(picker, { target: { value: "nova" } });
  fireEvent.click(screen.getByText("Ввести ID вручную — если поставщик ещё не в кэше"));
  fireEvent.change(screen.getByLabelText("ID сервиса у поставщика"), {
    target: { value: "steam-topup" },
  });
  fireEvent.change(screen.getByLabelText("Количество"), { target: { value: "1" } });

  const save = screen.getByRole("button", { name: "Сохранить" });
  expect(save).toBeEnabled();

  // And the narrowness: the same supplier with a real category is a game
  // mapping, which is useless without its offer id and must not save without
  // one — a mistake caught at the form beats one caught at a customer's order.
  fireEvent.change(screen.getByLabelText("ID сервиса у поставщика"), {
    target: { value: "pubg_mobile_auto" },
  });
  expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
});

it("drops the ids when the supplier changes", async () => {
  // Ids are per-supplier. Carrying one over would point G-Engine at a product
  // id that means something else in their catalogue — and it would save
  // without complaint.
  renderPage();
  const picker = await reachSupplierStep();

  fireEvent.change(picker, { target: { value: "gengine" } });
  fireEvent.click(screen.getByText("Ввести ID вручную — если поставщик ещё не в кэше"));
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
