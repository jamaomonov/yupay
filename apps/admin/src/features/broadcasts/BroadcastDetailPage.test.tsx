import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BroadcastDetailPage } from "./BroadcastDetailPage";

import type { BroadcastOut, RecipientListOut } from "./types";

import { apiGet, apiPost } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  ApiError: class MockApiError extends Error {
    status: number;
    statusText: string;
    body: unknown;
    constructor(status: number, statusText: string, body: unknown) {
      super(`${status.toString()} ${statusText}`);
      this.name = "ApiError";
      this.status = status;
      this.statusText = statusText;
      this.body = body;
    }
  },
}));

const mockedApiGet = vi.mocked(apiGet);
const mockedApiPost = vi.mocked(apiPost);

/** A broadcast mid-flight: some sent, one failed, one blocked, the rest pending. */
const SENDING_BROADCAST: BroadcastOut = {
  id: "b-1",
  title: "Летняя акция",
  status: "sending",
  body_html: "<b>Скидка 30%</b>",
  media_type: "none",
  media_url: null,
  media_file_id: null,
  locale_filter: null,
  disable_web_page_preview: false,
  scheduled_at: null,
  total_recipients: 500,
  sent_count: 448,
  failed_count: 1,
  blocked_count: 1,
  started_at: "2026-07-20T08:00:00Z",
  finished_at: null,
  last_error: null,
  created_by: "admin-aaaa1111",
  created_at: "2026-07-20T07:55:00Z",
  updated_at: "2026-07-20T08:05:00Z",
};

/** Terminal broadcast with no problem recipients — cancel button must not render. */
const SENT_BROADCAST: BroadcastOut = {
  ...SENDING_BROADCAST,
  id: "b-2",
  status: "sent",
  sent_count: 500,
  failed_count: 0,
  blocked_count: 0,
  finished_at: "2026-07-20T08:10:00Z",
};

/** Just-queued broadcast — audience not snapshotted yet (`total_recipients === 0`). */
const ZERO_TOTAL_BROADCAST: BroadcastOut = {
  ...SENDING_BROADCAST,
  id: "b-3",
  sent_count: 0,
  failed_count: 0,
  blocked_count: 0,
  total_recipients: 0,
};

const FAILED_RECIPIENTS: RecipientListOut = {
  items: [
    {
      user_id: "u-failed",
      tg_chat_id: "111111",
      status: "failed",
      error: "Bad Request: chat not found",
      sent_at: null,
    },
  ],
  total: 1,
};

const BLOCKED_RECIPIENTS: RecipientListOut = {
  items: [
    { user_id: "u-blocked", tg_chat_id: "222222", status: "blocked", error: null, sent_at: null },
  ],
  total: 1,
};

function renderPage(id: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/broadcasts/${id}`]}>
        <Routes>
          <Route path="/broadcasts/:id" element={<BroadcastDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("BroadcastDetailPage", () => {
  beforeEach(() => {
    mockedApiGet.mockReset();
    mockedApiPost.mockReset();
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  it("shows live counters and a Отменить отправку button for a sending broadcast, and clicking it posts to the cancel endpoint", async () => {
    mockedApiGet.mockImplementation((path: string) => {
      if (path.includes("/recipients?status=failed")) return Promise.resolve(FAILED_RECIPIENTS);
      if (path.includes("/recipients?status=blocked")) return Promise.resolve(BLOCKED_RECIPIENTS);
      if (path === "/api/v1/admin/broadcasts/b-1") return Promise.resolve(SENDING_BROADCAST);
      return Promise.reject(new Error(`unexpected apiGet call: ${path}`));
    });
    mockedApiPost.mockResolvedValue({ ...SENDING_BROADCAST, status: "canceled" });

    renderPage("b-1");

    // Counters render from the fetched detail.
    expect(await screen.findByText("448")).toBeInTheDocument(); // sent
    expect(screen.getByText("Обработано 450 из 500 (90%)")).toBeInTheDocument();

    const cancelButton = screen.getByRole("button", { name: "Отменить отправку" });
    fireEvent.click(cancelButton);

    await waitFor(() => {
      expect(mockedApiPost).toHaveBeenCalledWith(
        "/api/v1/admin/broadcasts/b-1/cancel",
        {},
        expect.objectContaining({ "Idempotency-Key": expect.any(String) as string }),
      );
    });
  });

  it("renders the failed/blocked recipients in a problem table", async () => {
    mockedApiGet.mockImplementation((path: string) => {
      if (path.includes("/recipients?status=failed")) return Promise.resolve(FAILED_RECIPIENTS);
      if (path.includes("/recipients?status=blocked")) return Promise.resolve(BLOCKED_RECIPIENTS);
      if (path === "/api/v1/admin/broadcasts/b-1") return Promise.resolve(SENDING_BROADCAST);
      return Promise.reject(new Error(`unexpected apiGet call: ${path}`));
    });

    renderPage("b-1");

    const table = await screen.findByRole("table", { name: "Проблемные получатели" });
    expect(within(table).getByText("111111")).toBeInTheDocument();
    expect(within(table).getByText("Bad Request: chat not found")).toBeInTheDocument();
    expect(within(table).getByText("222222")).toBeInTheDocument();
  });

  it("hides Отменить отправку for a terminal broadcast and never fetches problem recipients", async () => {
    mockedApiGet.mockImplementation((path: string) => {
      if (path === "/api/v1/admin/broadcasts/b-2") return Promise.resolve(SENT_BROADCAST);
      return Promise.reject(new Error(`unexpected apiGet call: ${path}`));
    });

    renderPage("b-2");

    await screen.findByRole("heading", { name: "Летняя акция" });
    expect(screen.queryByRole("button", { name: "Отменить отправку" })).not.toBeInTheDocument();
    expect(mockedApiGet).not.toHaveBeenCalledWith(expect.stringContaining("recipients"));
  });

  it("shows a neutral progress state instead of dividing by zero when total_recipients is 0", async () => {
    mockedApiGet.mockImplementation((path: string) => {
      if (path === "/api/v1/admin/broadcasts/b-3") return Promise.resolve(ZERO_TOTAL_BROADCAST);
      return Promise.reject(new Error(`unexpected apiGet call: ${path}`));
    });

    renderPage("b-3");

    expect(await screen.findByText("Запускается…")).toBeInTheDocument();
  });
});
