// @vitest-environment jsdom
import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CabinetProvider, useCabinet, useSearch } from "./CabinetContext";

let pathname = "/cabinet/catalog";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));
vi.mock("@/lib/api", () => ({ api: () => new Promise(() => undefined) }));

function Catalog() {
  useSearch("Игра или товар");
  return null;
}

function Settings() {
  return null;
}

let seen: string | null = "unset";
function Probe() {
  seen = useCabinet().searchPlaceholder;
  return null;
}

function App({ page }: { page: "catalog" | "settings" }) {
  return (
    <CabinetProvider>
      <Probe />
      {page === "catalog" ? <Catalog /> : <Settings />}
    </CabinetProvider>
  );
}

describe("cabinet search box", () => {
  beforeEach(() => {
    pathname = "/cabinet/catalog";
    seen = "unset";
  });

  it("comes back with the catalogue after a screen without search", () => {
    const view = render(<App page="catalog" />);
    expect(seen).toBe("Игра или товар");

    pathname = "/cabinet/settings";
    act(() => {
      view.rerender(<App page="settings" />);
    });
    expect(seen).toBeNull();

    pathname = "/cabinet/catalog";
    act(() => {
      view.rerender(<App page="catalog" />);
    });
    expect(seen).toBe("Игра или товар");
  });
});
