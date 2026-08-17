import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { PromoRedemptionsModal } from "./PromoRedemptionsModal";

import type { PromoRedemptionOut } from "./types";

import { apiGet } from "@/lib/api";

/**
 * The promo list showed "3 / 10" and nothing about who — the half of the
 * answer an operator never wanted. This is the other half, and it has to be
 * recognisable at a glance: a column of UUIDs would technically be the same
 * data and useless for spotting a person.
 */

vi.mock("@/lib/api", () => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
vi.mock("@/lib/useDialog", () => ({ useDialog: vi.fn() }));

const mockedApiGet = vi.mocked(apiGet);

function row(over: Partial<PromoRedemptionOut> = {}): PromoRedemptionOut {
  return {
    user_id: "019fd21a-0000-0000-0000-000000000000",
    display_name: "Jamshid",
    photo_url: "https://cdn.example.com/a.jpg",
    tg_username: "jam",
    email: "jam@example.com",
    redeemed_at: "2026-08-17T05:00:00Z",
    ...over,
  };
}

function renderModal(items: PromoRedemptionOut[], total = items.length) {
  mockedApiGet.mockResolvedValue({ items, total });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PromoRedemptionsModal promoId="promo-1" code="SUMMER10" onClose={vi.fn()} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
});

it("shows the person's face and name, linked to their profile", async () => {
  const { container } = renderModal([row()]);

  expect(await screen.findByText("Jamshid")).toBeInTheDocument();
  // `alt=""` on purpose: the name sits right beside it, so the avatar is
  // decorative and must not be announced twice — which is also why it has no
  // `img` role to query by.
  expect(container.querySelector("img")).toHaveAttribute("src", "https://cdn.example.com/a.jpg");
  expect(screen.getByRole("link", { name: /Jamshid/ })).toHaveAttribute(
    "href",
    "/customers/019fd21a-0000-0000-0000-000000000000",
  );
});

it("falls back through the identities an account might actually have", async () => {
  // A Telegram account has a name; an email-only one does not. Neither should
  // render as a blank row that looks broken.
  renderModal([
    row({ user_id: "u2", display_name: null, tg_username: "handle" }),
    row({ user_id: "u3", display_name: null, tg_username: null, email: "only@mail.com" }),
  ]);

  expect(await screen.findByText("@handle")).toBeInTheDocument();
  expect(screen.getByText("only@mail.com")).toBeInTheDocument();
});

it("draws an initial when there is no avatar", async () => {
  const { container } = renderModal([row({ photo_url: null })]);

  expect(await screen.findByText("Jamshid")).toBeInTheDocument();
  expect(container.querySelector("img")).toBeNull();
  expect(screen.getByText("J")).toBeInTheDocument();
});

it("says so when nobody has used the code", async () => {
  renderModal([]);

  expect(await screen.findByText(/никто не активировал/)).toBeInTheDocument();
});

it("admits when the list is capped rather than implying it is everything", async () => {
  renderModal([row()], 500);

  expect(await screen.findByText(/Показаны последние 1 из 500/)).toBeInTheDocument();
});
