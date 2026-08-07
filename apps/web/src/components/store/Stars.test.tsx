// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { Stars } from "./Stars";

test("labels the fractional value and renders both star rows", () => {
  const { container } = render(<Stars value={4.3} />);
  expect(screen.getByLabelText("4.3 / 5")).toBeInTheDocument();
  // 5 base + 5 overlay star glyphs.
  expect(container.querySelectorAll("svg")).toHaveLength(10);
});

test("exposes itself as one labelled image, not ten loose glyphs", () => {
  // ARIA forbids aria-label on a roleless element, so without role="img" the
  // label is dropped and the widget reaches assistive tech as bare stars.
  render(<Stars value={5} label="Рейтинг 5 из 5" />);
  expect(screen.getByRole("img", { name: "Рейтинг 5 из 5" })).toBeInTheDocument();
});
