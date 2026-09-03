// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { GiftsSettingsPage } from "./GiftsSettingsPage";

import type { GiftsAdminSettings } from "./types";

import { apiGet, apiPatch } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiPut: vi.fn(),
  // The page reads errors through `extractApiMessage`, which narrows on
  // `ApiError`; without it here the error branch throws instead of rendering.
  ApiError: class ApiError extends Error {},
}));

const mockedApiGet = vi.mocked(apiGet);
const mockedApiPatch = vi.mocked(apiPatch);

const SETTINGS: GiftsAdminSettings = {
  margin_percent: "10.0000",
  enabled: true,
  region_default: "CIS",
  regions: ["CIS", "RU", "KZ", "UA"],
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <GiftsSettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiPatch.mockReset();
  mockedApiGet.mockResolvedValue(SETTINGS);
});

it("renders the loaded margin, flag state and regions", async () => {
  renderPage();

  expect(await screen.findByDisplayValue("10.0000")).toBeInTheDocument();
  expect(screen.getByText("Включено")).toBeInTheDocument();
  expect(screen.getByText("RU")).toBeInTheDocument();
  expect(screen.getByText("UA")).toBeInTheDocument();
});

it("keeps save disabled until the margin value changes", async () => {
  renderPage();

  const input = await screen.findByDisplayValue("10.0000");
  const saveBtn = screen.getByRole("button", { name: "Сохранить" });
  expect(saveBtn).toBeDisabled();

  fireEvent.change(input, { target: { value: "12.5" } });
  expect(saveBtn).toBeEnabled();
});

it("keeps save disabled and shows a validation error for an out-of-range margin", async () => {
  renderPage();

  const input = await screen.findByDisplayValue("10.0000");
  const saveBtn = screen.getByRole("button", { name: "Сохранить" });

  fireEvent.change(input, { target: { value: "150" } });

  expect(saveBtn).toBeDisabled();
  expect(screen.getByText("Введите число от 0 до 100.")).toBeInTheDocument();
});

it("saves the typed margin with an Idempotency-Key header", async () => {
  mockedApiPatch.mockResolvedValue({ ...SETTINGS, margin_percent: "12.5" });
  renderPage();

  const input = await screen.findByDisplayValue("10.0000");
  fireEvent.change(input, { target: { value: "12.5" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

  await waitFor(() => {
    expect(mockedApiPatch).toHaveBeenCalledWith(
      "/api/v1/admin/gifts/settings",
      { margin_percent: "12.5" },
      expect.objectContaining({ "Idempotency-Key": expect.any(String) }),
    );
  });
});

it("shows the shared error state when the settings fetch fails", async () => {
  mockedApiGet.mockReset();
  mockedApiGet.mockRejectedValue(new Error("network down"));
  renderPage();

  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.getByText("Не удалось загрузить данные")).toBeInTheDocument();
});
