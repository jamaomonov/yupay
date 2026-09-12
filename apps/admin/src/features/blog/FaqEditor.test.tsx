// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { FaqEditor } from "./FaqEditor";

import type { FaqDraft } from "./form";

it("adds a blank pair for the active locale only", () => {
  const onChange = vi.fn<(items: FaqDraft[]) => void>();
  render(<FaqEditor locale="ru" items={[]} onChange={onChange} />);
  fireEvent.click(screen.getByRole("button", { name: /Добавить вопрос/ }));
  expect(onChange).toHaveBeenCalledWith([
    { locale: "ru", sort_order: 0, question: "", answer: "" },
  ]);
});
