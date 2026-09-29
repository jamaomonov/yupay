// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, it, vi } from "vitest";

import { SkinGridMore } from "./SkinGridMore";
import messages from "../../../../../packages/i18n/locales/ru/web.json";

import type * as Skins from "@/lib/skins";
import type { SkinItem, SkinsPage } from "@/lib/skins";

type SkinsModule = typeof Skins;

const fetchSkinsPage = vi.fn<(locale: string, q: unknown) => Promise<SkinsPage>>();
vi.mock("@/lib/skins", async (orig) => ({
  ...(await orig<SkinsModule>()),
  fetchSkinsPage: (locale: string, q: unknown) => fetchSkinsPage(locale, q),
}));

let intersect: () => void = () => undefined;
class FakeObserver {
  constructor(cb: IntersectionObserverCallback) {
    intersect = () => {
      // Only the fields the component reads; the rest of the entry is irrelevant here.
      cb([{ isIntersecting: true } as IntersectionObserverEntry], this as never);
    };
  }
  observe(): void {
    // Nothing to watch: the test fires `intersect` itself.
  }
  disconnect(): void {
    intersect = () => undefined;
  }
}

function skin(slug: string): SkinItem {
  return {
    slug,
    name: slug,
    phase: null,
    category: "rifles",
    weapon: "AK-47",
    skin: slug,
    exterior: "FT",
    stattrak: false,
    souvenir: false,
    rarity: "Classified",
    rarity_color: "#d32ce6",
    image_url: "https://community.akamai.steamstatic.com/economy/image/x",
    price_usd: "1",
    price_uzs: "12700",
    steam_price_usd: null,
    discount_percent: null,
    count: 1,
    min_float: null,
    max_float: null,
  };
}

function renderMore() {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      <ul>
        <SkinGridMore query={{ sort: "-price" }} cursor="c1" locale="ru" shown={["a"]} />
      </ul>
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  fetchSkinsPage.mockReset();
  vi.stubGlobal("IntersectionObserver", FakeObserver);
});

it("appends the next batch when the reader nears the end, without repeating a card", async () => {
  let resolve: (p: SkinsPage) => void = () => undefined;
  fetchSkinsPage.mockReturnValueOnce(new Promise((r) => (resolve = r)));
  renderMore();
  act(() => {
    intersect();
  });
  expect(screen.getByRole("status")).toBeInTheDocument();
  expect(fetchSkinsPage).toHaveBeenCalledWith("ru", { sort: "-price", cursor: "c1" });
  await act(() => {
    resolve({ items: [skin("a"), skin("b")], next_cursor: "c2" });
    return Promise.resolve();
  });
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.getAllByRole("listitem")).toHaveLength(2); // "b" + the loader row; "a" was on the server page
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("offers a retry when a batch fails", async () => {
  fetchSkinsPage.mockRejectedValueOnce(new Error("down"));
  fetchSkinsPage.mockResolvedValueOnce({ items: [skin("b")], next_cursor: null });
  renderMore();
  act(() => {
    intersect();
  });
  const retry = await screen.findByRole("button", { name: "Показать ещё" });
  fireEvent.click(retry);
  await waitFor(() => {
    expect(screen.getAllByRole("listitem")).toHaveLength(2); // "b" + the loader row
  });
});
