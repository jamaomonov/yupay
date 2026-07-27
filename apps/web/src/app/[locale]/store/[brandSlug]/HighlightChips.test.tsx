// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { HighlightChips } from "./HighlightChips";

test("renders a chip per highlight", () => {
  render(<HighlightChips items={["0% комиссии", "Оплата в сумах"]} />);
  expect(screen.getByText("0% комиссии")).toBeInTheDocument();
  expect(screen.getByText("Оплата в сумах")).toBeInTheDocument();
});

test("renders nothing when empty", () => {
  const { container } = render(<HighlightChips items={[]} />);
  expect(container).toBeEmptyDOMElement();
});
