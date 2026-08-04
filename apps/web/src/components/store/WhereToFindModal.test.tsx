// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { WhereToFindModal } from "./WhereToFindModal";

const props = {
  title: "Где найти ID",
  body: "Строка 1\nСтрока 2",
  closeLabel: "Закрыть",
};

test("renders nothing when closed", () => {
  const { container } = render(<WhereToFindModal open={false} onClose={vi.fn()} {...props} />);
  expect(container).toBeEmptyDOMElement();
});

test("shows title and body when open", () => {
  render(<WhereToFindModal open onClose={vi.fn()} {...props} />);
  expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
  expect(screen.getByRole("heading", { name: "Где найти ID" })).toBeInTheDocument();
  // Newline-separated body renders as one pre-line block.
  expect(screen.getByText(/Строка 1/)).toBeInTheDocument();
});

test("closes on the X button and on Escape", () => {
  const onClose = vi.fn();
  render(<WhereToFindModal open onClose={onClose} {...props} />);

  fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
  expect(onClose).toHaveBeenCalledTimes(1);

  fireEvent.keyDown(document, { key: "Escape" });
  expect(onClose).toHaveBeenCalledTimes(2);
});
