import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BroadcastComposerPage } from "./BroadcastComposerPage";

import type { AudienceCountOut } from "./types";

import { apiGet, apiPatch, apiPost } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
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
const mockedApiPatch = vi.mocked(apiPatch);

const AUDIENCE: AudienceCountOut = { count: 4812 };

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/broadcasts/new"]}>
        <BroadcastComposerPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("BroadcastComposerPage", () => {
  beforeEach(() => {
    mockedApiGet.mockReset();
    mockedApiPost.mockReset();
    mockedApiPatch.mockReset();
    mockedApiGet.mockImplementation((path: string) => {
      if (path.includes("audience-count")) return Promise.resolve(AUDIENCE);
      return Promise.reject(new Error(`unexpected apiGet call: ${path}`));
    });
  });

  it("shows a typed title and body in the live preview column", () => {
    renderPage();

    fireEvent.change(screen.getByLabelText("Заголовок", { exact: false }), {
      target: { value: "Летняя акция" },
    });

    const editor = screen.getByRole("textbox", { name: "Текст рассылки" });
    fireEvent.input(editor, { target: { textContent: "Скидка 30% только сегодня!" } });

    // The title is admin-only chrome above the phone bubble (Telegram never
    // sees it) — asserted unscoped since it's unique on the page.
    expect(screen.getByText("Летняя акция")).toBeInTheDocument();

    // The body is what the recipient actually reads, rendered both by
    // TelegramEditor's own inline preview and by BroadcastPreview's phone
    // bubble — scope to the bubble (`BroadcastPreview`'s "Как увидит
    // получатель" card) so the assertion targets this composer's own
    // preview column, not the editor's internal one.
    const bubble = screen.getByText("Как увидит получатель").closest("section");
    if (!bubble) throw new Error("preview bubble section not found");
    expect(within(bubble).getByText("Скидка 30% только сегодня!")).toBeInTheDocument();
  });

  it("opens a confirm dialog showing the live audience count when Отправить is clicked", async () => {
    renderPage();

    fireEvent.change(screen.getByLabelText("Заголовок", { exact: false }), {
      target: { value: "Летняя акция" },
    });
    const editor = screen.getByRole("textbox", { name: "Текст рассылки" });
    fireEvent.input(editor, { target: { textContent: "Привет!" } });

    // Wait for the audience-count query to resolve so the number is on the
    // page (and therefore available to the dialog) before clicking.
    expect(await screen.findByText("4812")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Отправить" }));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("4812");
    expect(dialog).toHaveTextContent("Отправить рассылку сейчас?");

    // Confirming isn't exercised here — only the confirm-dialog contract
    // (audience count surfaced before any write happens).
    expect(mockedApiPost).not.toHaveBeenCalled();
    expect(mockedApiPatch).not.toHaveBeenCalled();
  });

  it("disables Отправить when the body is empty and no media is attached", () => {
    renderPage();

    fireEvent.change(screen.getByLabelText("Заголовок", { exact: false }), {
      target: { value: "Летняя акция" },
    });

    expect(screen.getByRole("button", { name: "Отправить" })).toBeDisabled();
  });
});
