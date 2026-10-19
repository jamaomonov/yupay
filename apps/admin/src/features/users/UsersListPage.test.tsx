// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { UsersListPage } from "./UsersListPage";

import type { UserAdminListOut, UserAdminOut } from "./types";

import { apiGet } from "@/lib/api";

/**
 * The page paged forward and then bounced straight back to the first page a
 * quarter of a second later.
 *
 * Its local `useDebounce` listed `callback` in the effect's dependencies, and
 * the caller passed a fresh arrow on every render — so the effect re-armed on
 * *every* render, not only when the search text changed, and its body reset
 * the offset to 0. Pressing "Вперёд" re-rendered, which re-armed the timer,
 * which put the reader back on page one.
 */

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockedApiGet = vi.mocked(apiGet);

const PAGE_SIZE = 50;

function makeUser(i: number): UserAdminOut {
  return {
    id: `01a004c3-0000-0000-0000-${String(i).padStart(12, "0")}`,
    email: `user${String(i)}@example.com`,
    locale: "ru",
    display_currency: "UZS",
    display_name: `User ${String(i)}`,
    photo_url: null,
    roles: [],
    signup_source: "miniapp",
    created_at: "2026-08-15T13:26:00Z",
    updated_at: "2026-08-15T13:26:00Z",
    deleted_at: null,
    banned_at: null,
    ban_reason: null,
    banned_by: null,
    purchase_limit_usd: null,
    trusted_at: null,
    trusted_by: null,
    telegram_link: null,
    steam_link: null,
    wallet_balances: [],
  };
}

/** Two full pages, so "Вперёд" is enabled. */
function renderPage(entry = "/users") {
  mockedApiGet.mockImplementation((url: string) => {
    const offset = Number(new URL(url, "http://x").searchParams.get("offset") ?? "0");
    const payload: UserAdminListOut = {
      items: Array.from({ length: PAGE_SIZE }, (_, i) => makeUser(offset + i)),
      total: PAGE_SIZE * 2,
      wallet_totals: [{ currency: "USD", balance: "10.00" }],
    };
    return Promise.resolve(payload);
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <UsersListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function lastOffset(): number {
  const calls = mockedApiGet.mock.calls;
  const url = calls[calls.length - 1]?.[0];
  if (typeof url !== "string") throw new Error("expected a request");
  return Number(new URL(url, "http://x").searchParams.get("offset") ?? "0");
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  mockedApiGet.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

it("stays on the second page after the debounce window elapses", async () => {
  renderPage();
  await waitFor(() => {
    expect(mockedApiGet).toHaveBeenCalled();
  });

  fireEvent.click(await screen.findByRole("button", { name: "Следующая страница" }));
  await waitFor(() => {
    expect(lastOffset()).toBe(PAGE_SIZE);
  });

  // Long enough for the old re-armed timer to have fired.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });

  expect(lastOffset()).toBe(PAGE_SIZE);
  expect(await screen.findByText(`51–100 из ${String(PAGE_SIZE * 2)}`)).toBeInTheDocument();
});

it("returns to the first page when the search changes", async () => {
  renderPage();
  await waitFor(() => {
    expect(mockedApiGet).toHaveBeenCalled();
  });

  fireEvent.click(await screen.findByRole("button", { name: "Следующая страница" }));
  await waitFor(() => {
    expect(lastOffset()).toBe(PAGE_SIZE);
  });

  fireEvent.change(screen.getByPlaceholderText(/поиск/i), { target: { value: "user7" } });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });

  await waitFor(() => {
    expect(lastOffset()).toBe(0);
  });
});

it("restores search, sort and page from the URL when the operator comes back", async () => {
  renderPage("/users?q=jam&sort=wallet_desc&offset=50");

  await waitFor(() => {
    expect(mockedApiGet).toHaveBeenCalled();
  });
  const url = new URL(mockedApiGet.mock.calls[0]?.[0] ?? "", "http://x");
  expect(url.searchParams.get("search")).toBe("jam");
  expect(url.searchParams.get("sort")).toBe("wallet_desc");
  expect(url.searchParams.get("offset")).toBe("50");
  expect(screen.getByPlaceholderText("Поиск…")).toHaveValue("jam");
  expect(screen.getByLabelText("Сортировка")).toHaveValue("wallet_desc");

  // The debounce settling on the restored text must not throw the page back to one.
  await act(async () => {
    await new Promise((r) => setTimeout(r, 400));
  });
  const last = mockedApiGet.mock.calls.at(-1)?.[0] ?? "";
  expect(new URL(last, "http://x").searchParams.get("offset")).toBe("50");
});
