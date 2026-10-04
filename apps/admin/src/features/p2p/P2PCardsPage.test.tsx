// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { P2PCardsPage } from "./P2PCardsPage";

import type { P2PCard, P2PSettings } from "./api";

import { apiGet, apiPatch, apiPost } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiPut: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const get = vi.mocked(apiGet);
const patch = vi.mocked(apiPatch);
const post = vi.mocked(apiPost);

const SETTINGS: P2PSettings = {
  mode: "off",
  allowlist_merchant_ids: [],
  humo_bot_user_id: null,
  owner_telegram_user_id: null,
  business_connection_id: null,
  updated_at: "2026-10-04T10:00:00Z",
};
const CARD: P2PCard = {
  id: "c1",
  label: "Основная",
  pan_last4: "3311",
  holder_name: "A B",
  network: "humo",
  active: true,
  min_amount_uzs: 10000,
  max_amount_uzs: 10000000,
  daily_limit_uzs: null,
  matched_today_uzs: 150000,
  last_incoming_at: null,
  chain_ok_last: false,
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <P2PCardsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  patch.mockReset();
  post.mockReset();
  get.mockImplementation((path: string) =>
    Promise.resolve(path.endsWith("/settings") ? SETTINGS : [CARD]),
  );
});

it("shows the card by its last four digits only", async () => {
  renderPage();
  expect(await screen.findByText("*3311")).toBeInTheDocument();
  expect(screen.getByText("разрыв баланса")).toBeInTheDocument();
  expect(document.body.textContent).not.toMatch(/\d{16}/);
});

it("saves settings with an Idempotency-Key header", async () => {
  patch.mockResolvedValue({ ...SETTINGS, mode: "all" });
  renderPage();
  await screen.findByText("*3311");
  fireEvent.change(screen.getByRole("combobox", { name: /Кому доступно/ }), {
    target: { value: "all" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
  await waitFor(() => {
    expect(patch).toHaveBeenCalledWith(
      "/api/v1/admin/p2p/settings",
      expect.objectContaining({ mode: "all" }),
      expect.objectContaining({ "Idempotency-Key": expect.any(String) as string }),
    );
  });
});

it("edits a card without sending the number unless a new one is typed", async () => {
  patch.mockResolvedValue(CARD);
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "Изменить" }));
  expect(screen.getByPlaceholderText("•••• 3311")).toHaveValue("");
  fireEvent.change(screen.getByDisplayValue("Основная"), { target: { value: "Запасная" } });
  fireEvent.click(within(screen.getByRole("form")).getByRole("button", { name: "Сохранить" }));
  await waitFor(() => {
    expect(patch).toHaveBeenCalled();
  });
  const body = patch.mock.calls.find(([p]) => p.includes("/cards/"))?.[1] as Record<
    string,
    unknown
  >;
  expect(body).toMatchObject({ label: "Запасная" });
  expect(body).not.toHaveProperty("pan");
});

const PAN = "9860123456783311";

it("sends a typed number once, then never shows it again", async () => {
  patch.mockResolvedValue(CARD);
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "Изменить" }));
  fireEvent.change(screen.getByPlaceholderText("•••• 3311"), { target: { value: PAN } });
  fireEvent.click(within(screen.getByRole("form")).getByRole("button", { name: "Сохранить" }));
  await waitFor(() => {
    expect(patch).toHaveBeenCalled();
  });
  const body = patch.mock.calls.find(([p]) => p.includes("/cards/"))?.[1] as Record<
    string,
    unknown
  >;
  expect(body).toHaveProperty("pan", PAN);
  await waitFor(() => {
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
  });
  expect(document.body.textContent).not.toContain(PAN);
  // Reopening the form: the number field starts empty again.
  fireEvent.click(await screen.findByRole("button", { name: "Изменить" }));
  expect(screen.getByPlaceholderText("•••• 3311")).toHaveValue("");
});

it("reuses the Idempotency-Key when a failed add is retried, and drops it after an edit", async () => {
  post.mockRejectedValue(new Error("network down"));
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "Добавить карту" }));
  const form = screen.getByRole("form");
  const [labelInput, panInput, holderInput] = within(form).getAllByRole("textbox");
  if (!labelInput || !panInput || !holderInput) throw new Error("card form inputs missing");
  fireEvent.change(labelInput, { target: { value: "Новая" } });
  fireEvent.change(panInput, { target: { value: PAN } });
  fireEvent.change(holderInput, { target: { value: "A B" } });
  const save = () => {
    fireEvent.click(within(form).getByRole("button", { name: "Сохранить" }));
  };
  const keyOf = (n: number) =>
    (post.mock.calls[n]?.[2] as Record<string, string> | undefined)?.["Idempotency-Key"];

  save();
  await waitFor(() => {
    expect(post).toHaveBeenCalledTimes(1);
  });
  expect(keyOf(0)).toEqual(expect.any(String));
  await screen.findByRole("alert");
  save();
  await waitFor(() => {
    expect(post).toHaveBeenCalledTimes(2);
  });
  expect(keyOf(1)).toBe(keyOf(0));

  fireEvent.change(labelInput, { target: { value: "Другая" } });
  save();
  await waitFor(() => {
    expect(post).toHaveBeenCalledTimes(3);
  });
  expect(keyOf(2)).not.toBe(keyOf(0));
});

it("shows whether the owner's Business connection is pinned", async () => {
  renderPage();
  expect(await screen.findByText("не подключено")).toBeInTheDocument();
});

it("shows the pinned connection id and saves the owner's Telegram id", async () => {
  get.mockImplementation((path: string) =>
    Promise.resolve(
      path.endsWith("/settings")
        ? { ...SETTINGS, owner_telegram_user_id: 555, business_connection_id: "bc-owner" }
        : [CARD],
    ),
  );
  patch.mockResolvedValue({ ...SETTINGS, owner_telegram_user_id: 777 });
  renderPage();
  expect(await screen.findByText(/^подключено/)).toBeInTheDocument();
  expect(screen.getByText("bc-owner")).toBeInTheDocument();
  const owner = screen.getByRole("textbox", { name: /владелец карты/ });
  expect(owner).toHaveValue("555");
  fireEvent.change(owner, { target: { value: "777" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
  await waitFor(() => {
    expect(patch).toHaveBeenCalledWith(
      "/api/v1/admin/p2p/settings",
      expect.objectContaining({ owner_telegram_user_id: 777 }),
      expect.anything(),
    );
  });
  const body = patch.mock.calls[0]?.[1] as Record<string, unknown>;
  expect(body).not.toHaveProperty("business_connection_id");
});

it("reuses the settings Idempotency-Key when a failed save is retried unedited", async () => {
  patch.mockRejectedValue(new Error("network down"));
  renderPage();
  await screen.findByText("*3311");
  fireEvent.change(screen.getByRole("combobox", { name: /Кому доступно/ }), {
    target: { value: "all" },
  });
  const keyOf = (n: number) =>
    (patch.mock.calls[n]?.[2] as Record<string, string> | undefined)?.["Idempotency-Key"];
  const save = () => {
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
  };
  save();
  await waitFor(() => {
    expect(patch).toHaveBeenCalledTimes(1);
  });
  await screen.findByRole("alert");
  save();
  await waitFor(() => {
    expect(patch).toHaveBeenCalledTimes(2);
  });
  expect(keyOf(0)).toEqual(expect.any(String));
  expect(keyOf(1)).toBe(keyOf(0));
});
