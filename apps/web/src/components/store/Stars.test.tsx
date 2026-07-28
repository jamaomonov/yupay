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
