// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { UsdtNetworkCard } from "./UsdtNetworkCard";

import type { UsdtNetwork, UsdtSettings } from "./api";

import { apiPatch } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiPut: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const patch = vi.mocked(apiPatch);

const BEP20: UsdtNetwork = {
  network: "bep20",
  enabled: false,
  address: "0xAbCdEf0123456789aBcDeF0123456789AbCdEf01",
  cursor: 4242,
  updated_at: "2026-11-11T10:00:00Z",
};
const NEW_ADDRESS = "0x52908400098527886E0F7030069857D2E4169EE7";

function settingsWith(n: UsdtNetwork): UsdtSettings {
  return {
    mode: "all",
    allowlist_merchant_ids: [],
    min_amount_usd: "10",
    max_amount_usd: "1000",
    updated_at: "2026-11-11T10:00:00Z",
    networks: [n],
  };
}

function renderCard(network: UsdtNetwork) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <UsdtNetworkCard network={network} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  patch.mockReset();
});

it("shows the poll cursor, or that it starts from the current block", () => {
  const { unmount } = renderCard(BEP20);
  expect(screen.getByText("Читаем с блока 4242")).toBeInTheDocument();
  unmount();
  renderCard({ ...BEP20, cursor: null });
  expect(screen.getByText("Начнём с текущего блока")).toBeInTheDocument();
});

it("toggling only sends `enabled`, without a confirm", async () => {
  patch.mockResolvedValue(settingsWith({ ...BEP20, enabled: true }));
  renderCard(BEP20);
  fireEvent.click(screen.getByRole("checkbox", { name: "Включена" }));
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
  await waitFor(() => {
    expect(patch).toHaveBeenCalledWith(
      "/api/v1/admin/usdt/networks/bep20",
      { enabled: true },
      expect.objectContaining({ "Idempotency-Key": expect.any(String) as string }),
    );
  });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("a changed address is confirmed first — it closes the chain's reservations", async () => {
  patch.mockResolvedValue(settingsWith({ ...BEP20, address: NEW_ADDRESS }));
  renderCard(BEP20);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: ` ${NEW_ADDRESS} ` } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
  const dialog = await screen.findByRole("dialog");
  expect(dialog).toHaveTextContent("резервы этой сети будут закрыты");
  expect(patch).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole("button", { name: "Сменить адрес" }));
  await waitFor(() => {
    expect(patch).toHaveBeenCalledWith(
      "/api/v1/admin/usdt/networks/bep20",
      { address: NEW_ADDRESS },
      expect.objectContaining({ "Idempotency-Key": expect.any(String) as string }),
    );
  });
});

it("warns when the chain is enabled with no address", () => {
  renderCard({ ...BEP20, enabled: true, address: null });
  expect(screen.getByRole("status")).toHaveTextContent("адрес не указан");
});
