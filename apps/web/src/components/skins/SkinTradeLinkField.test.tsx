// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, it, vi } from "vitest";

import { SkinTradeLinkField } from "./SkinTradeLinkField";
import messages from "../../../../../packages/i18n/locales/ru/web.json";

import type * as SkinsModule from "@/lib/skins";

import { checkTradeLink, getTradeLink } from "@/lib/skins";

vi.mock("@/lib/skins", async (importOriginal) => ({
  ...(await importOriginal<typeof SkinsModule>()),
  getTradeLink: vi.fn(),
  checkTradeLink: vi.fn(),
}));

const LINK = "https://steamcommunity.com/tradeoffer/new/?partner=1039652352&token=LBCWEQ8s";

function field(onChange = vi.fn()) {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      <SkinTradeLinkField signedIn onChange={onChange} />
    </NextIntlClientProvider>,
  );
  return onChange;
}

beforeEach(() => {
  vi.mocked(getTradeLink).mockReset();
  vi.mocked(checkTradeLink).mockReset();
});

it("prefills the saved link and reports it usable once checked", async () => {
  vi.mocked(getTradeLink).mockResolvedValue(LINK);
  vi.mocked(checkTradeLink).mockResolvedValue({ ok: true, reason: null });
  const onChange = field();
  expect(await screen.findByDisplayValue(LINK)).toBeInTheDocument();
  await waitFor(() => {
    expect(onChange).toHaveBeenLastCalledWith({ url: LINK, usable: true });
  });
  expect(screen.getByText("Ссылка работает")).toBeInTheDocument();
});

it("names a private inventory and blocks", async () => {
  vi.mocked(getTradeLink).mockResolvedValue(null);
  vi.mocked(checkTradeLink).mockResolvedValue({ ok: false, reason: "private" });
  const onChange = field();
  fireEvent.change(await screen.findByLabelText("Трейд-ссылка Steam"), {
    target: { value: LINK },
  });
  expect(await screen.findByText(/Инвентарь скрыт/)).toBeInTheDocument();
  expect(onChange).toHaveBeenLastCalledWith({ url: LINK, usable: false });
});

it("lets an unavailable check through without a message", async () => {
  vi.mocked(getTradeLink).mockResolvedValue(null);
  vi.mocked(checkTradeLink).mockResolvedValue({ ok: true, reason: "unavailable" });
  const onChange = field();
  fireEvent.change(await screen.findByLabelText("Трейд-ссылка Steam"), {
    target: { value: LINK },
  });
  await waitFor(() => {
    expect(onChange).toHaveBeenLastCalledWith({ url: LINK, usable: true });
  });
});

it("does not call the check for text that is not a trade link", async () => {
  vi.mocked(getTradeLink).mockResolvedValue(null);
  const onChange = field();
  fireEvent.change(await screen.findByLabelText("Трейд-ссылка Steam"), {
    target: { value: "hello" },
  });
  expect(await screen.findByText("Это не трейд-ссылка Steam")).toBeInTheDocument();
  expect(checkTradeLink).not.toHaveBeenCalled();
  expect(onChange).toHaveBeenLastCalledWith({ url: "hello", usable: false });
});

it("never replaces a link pasted before the saved one arrives", async () => {
  let answer: (v: string) => void = () => undefined;
  vi.mocked(getTradeLink).mockReturnValue(
    new Promise<string>((resolve) => {
      answer = resolve;
    }),
  );
  vi.mocked(checkTradeLink).mockResolvedValue({ ok: true, reason: null });
  field();
  const pasted = "https://steamcommunity.com/tradeoffer/new/?partner=42&token=pastedAB";
  fireEvent.change(screen.getByRole("textbox"), { target: { value: pasted } });
  answer(LINK);
  await waitFor(() => {
    expect(getTradeLink).toHaveBeenCalled();
  });
  await new Promise((r) => setTimeout(r, 0));
  expect(screen.getByRole("textbox")).toHaveValue(pasted);
});
