// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { SkinPriceFilter } from "./SkinPriceFilter";
import messages from "../../../../../packages/i18n/locales/ru/web.json";

const { replaceMock } = vi.hoisted(() => ({ replaceMock: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: replaceMock }) }));

function filter() {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      <SkinPriceFilter query={{ sort: "-price", category: "rifles", minUzs: 1000 }} locale="ru" />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  replaceMock.mockReset();
});
afterEach(() => {
  vi.useRealTimers();
});

it("applies a typed price once typing pauses, with no button to press", () => {
  filter();
  expect(screen.queryByRole("button", { name: "Применить" })).not.toBeInTheDocument();
  const to = screen.getByPlaceholderText("До");
  fireEvent.change(to, { target: { value: "5" } });
  fireEvent.change(to, { target: { value: "50000" } });
  act(() => {
    vi.advanceTimersByTime(499);
  });
  expect(replaceMock).not.toHaveBeenCalled();
  act(() => {
    vi.advanceTimersByTime(1);
  });
  expect(replaceMock).toHaveBeenCalledTimes(1);
  const url = String(replaceMock.mock.calls[0]![0]);
  expect(url).toContain("max=50000");
  expect(url).toContain("min=1000");
  expect(url).toContain("category=rifles");
});

it("drops a bound that was cleared", () => {
  filter();
  fireEvent.change(screen.getByPlaceholderText("От"), { target: { value: "" } });
  act(() => {
    vi.advanceTimersByTime(500);
  });
  expect(String(replaceMock.mock.calls[0]![0])).not.toContain("min=");
});
