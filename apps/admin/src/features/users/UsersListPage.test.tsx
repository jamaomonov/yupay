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
    email: `user${i}@example.com`,
    locale: "ru",
    display_currency: "UZS",
    display_name: `User ${i}`,
    photo_url: null,
    roles: [],
    created_at: "2026-08-15T13:26:00Z",
    updated_at: "2026-08-15T13:26:00Z",
    deleted_at: null,
    banned_at: null,
    ban_reason: null,
    banned_by: null,
    telegram_link: null,
  steam_link: null,
  };
}

/** Two full pages, so "Вперёд" is enabled. */
function renderPage() {
  mockedApiGet.mockImplementation((url: string) => {
    const offset = Number(new URL(url, "http://x").searchParams.get("offset") ?? "0");
    const payload: UserAdminListOut = {
      items: Array.from({ length: PAGE_SIZE }, (_, i) => makeUser(offset + i)),
      total: PAGE_SIZE * 2,
    };
    return Promise.resolve(payload) as ReturnType<typeof apiGet>;
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/users"]}>
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
  expect(await screen.findByText(`51–100 из ${PAGE_SIZE * 2}`)).toBeInTheDocument();
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
