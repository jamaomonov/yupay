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

test("styles for the surface it is placed on", () => {
  // The hero variant is built for a photograph behind it; the same classes on
  // the gifts hub, which has none, are white-on-white in the light theme.
  const { container: onImage } = render(<HighlightChips items={["a"]} />);
  const { container: onSurface } = render(<HighlightChips items={["a"]} variant="on-surface" />);
  expect(onImage.firstElementChild?.className).toContain("bg-black/45");
  expect(onSurface.firstElementChild?.className).not.toContain("bg-black/45");
});

test("renders nothing when empty", () => {
  const { container } = render(<HighlightChips items={[]} />);
  expect(container).toBeEmptyDOMElement();
});
