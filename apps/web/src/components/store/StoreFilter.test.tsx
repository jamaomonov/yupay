// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it } from "vitest";

import { StoreFilter } from "./StoreFilter";

const chips = [
  { slug: "all", label: "Все" },
  { slug: "games", label: "Игры" },
];
const items = [
  { key: "pubg-mobile", category: "games", name: "PUBG Mobile", node: <a key="p">PUBG</a> },
  { key: "steam", category: "wallets", name: "Steam", node: <a key="s">Steam</a> },
];

const lists = (): unknown[] =>
  (window.dataLayer ?? []).filter(
    (e) => typeof e === "object" && e !== null && "event" in e && e.event === "view_item_list",
  );

beforeEach(() => {
  delete window.dataLayer;
  window.history.replaceState(null, "", "/store");
});

function renderFilter() {
  return render(
    <StoreFilter locale="ru" chips={chips} items={items} emptyLabel="—" searchLabel="Поиск" />,
  );
}

it("sends view_item_list once for the category on screen, and nothing for a search", () => {
  window.history.replaceState(null, "", "/store?cat=games");
  const { rerender } = renderFilter();
  rerender(
    <StoreFilter locale="ru" chips={chips} items={items} emptyLabel="—" searchLabel="Поиск" />,
  );
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "ste" } });

  expect(lists()).toEqual([
    {
      event: "view_item_list",
      ecommerce: {
        item_list_id: "games",
        item_list_name: "Игры",
        items: [
          { item_id: "pubg-mobile", item_name: "PUBG Mobile", item_brand: "pubg-mobile", index: 0 },
        ],
      },
    },
  ]);
});

it("lists the whole catalogue without a category", () => {
  renderFilter();
  expect(lists()).toHaveLength(1);
  expect(lists()[0]).toMatchObject({ ecommerce: { item_list_id: "all" } });
});
