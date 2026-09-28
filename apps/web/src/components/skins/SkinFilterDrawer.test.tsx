// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import Link from "next/link";
import { NextIntlClientProvider } from "next-intl";
import { expect, it } from "vitest";

import { SkinFilterDrawer } from "./SkinFilterDrawer";
import messages from "../../../../../packages/i18n/locales/ru/web.json";

function drawer() {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      <SkinFilterDrawer count={0}>
        <Link href="/skins?exterior=FT">После полевых</Link>
      </SkinFilterDrawer>
    </NextIntlClientProvider>,
  );
  return screen.getByRole("button", { name: "Фильтры" });
}

it("moves focus into the drawer on open and back to the trigger on close", () => {
  const trigger = drawer();
  fireEvent.click(trigger);
  const dialog = screen.getByRole("dialog");
  expect(dialog).toContainElement(document.activeElement as HTMLElement);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});

it("keeps the backdrop out of the tab order and names one close control", () => {
  fireEvent.click(drawer());
  expect(screen.getAllByRole("button", { name: "Готово" })).toHaveLength(1);
});

it("restores the page's own overflow lock on close", () => {
  document.body.style.overflow = "clip";
  fireEvent.click(drawer());
  fireEvent.keyDown(document, { key: "Escape" });
  expect(document.body.style.overflow).toBe("clip");
  document.body.style.overflow = "";
});
