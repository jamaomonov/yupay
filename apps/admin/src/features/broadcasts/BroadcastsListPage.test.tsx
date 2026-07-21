import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BroadcastsListPage } from "./BroadcastsListPage";

import type { BroadcastListOut } from "./types";

import { apiGet } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
}));

const mockedApiGet = vi.mocked(apiGet);

/** Two rows spanning distinct FSM states so the test can assert both the
 * title text and a status-badge label render from the fetched list. */
const LIST: BroadcastListOut = {
  items: [
    {
      id: "b-1",
      title: "Летняя распродажа",
      status: "sent",
      body_html: "<b>Скидки до 30%</b>",
      media_type: "none",
      media_url: null,
      media_file_id: null,
      locale_filter: null,
      disable_web_page_preview: false,
      scheduled_at: null,
      total_recipients: 1200,
      sent_count: 1150,
      failed_count: 30,
      blocked_count: 20,
      started_at: "2026-07-01T08:00:00Z",
      finished_at: "2026-07-01T08:12:00Z",
      last_error: null,
      created_by: "admin-aaaa1111",
      created_at: "2026-07-01T07:55:00Z",
      updated_at: "2026-07-01T08:12:00Z",
    },
    {
      id: "b-2",
      title: "Черновик анонса",
      status: "draft",
      body_html: "<i>скоро</i>",
      media_type: "none",
      media_url: null,
      media_file_id: null,
      locale_filter: "ru",
      disable_web_page_preview: false,
      scheduled_at: null,
      total_recipients: 0,
      sent_count: 0,
      failed_count: 0,
      blocked_count: 0,
      started_at: null,
      finished_at: null,
      last_error: null,
      created_by: "admin-bbbb2222",
      created_at: "2026-07-05T10:00:00Z",
      updated_at: "2026-07-05T10:00:00Z",
    },
  ],
  total: 2,
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <BroadcastsListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("BroadcastsListPage", () => {
  beforeEach(() => {
    mockedApiGet.mockReset();
    mockedApiGet.mockResolvedValue(LIST);
  });

  it("renders both broadcast titles and a status badge for each", async () => {
    renderPage();

    expect(await screen.findByText("Летняя распродажа")).toBeInTheDocument();
    expect(screen.getByText("Черновик анонса")).toBeInTheDocument();

    // Scope the badge-label assertions to the table: the status-filter
    // `<select>` also has options reading "Отправлено" / "Черновик", so an
    // unscoped `getByText` would ambiguously match both.
    const table = within(screen.getByRole("table"));
    expect(table.getByText("Отправлено")).toBeInTheDocument();
    expect(table.getByText("Черновик")).toBeInTheDocument();
  });

  it("fetches the admin broadcasts list endpoint", async () => {
    renderPage();

    await screen.findByText("Летняя распродажа");
    expect(mockedApiGet).toHaveBeenCalledWith(expect.stringContaining("/api/v1/admin/broadcasts"));
  });
});
