// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { Thumb } from "./Thumb";

/**
 * The catalogue lists identified rows by name alone, so finding one meant
 * reading every row. The picture is a second, faster handle on the same row —
 * which only works if it is never a hole in the layout.
 */

it("shows the picture when there is one", () => {
  render(<Thumb src="https://cdn.example/x.png" name="Roblox" />);
  expect(screen.getByRole("presentation", { hidden: true })).toHaveAttribute(
    "src",
    "https://cdn.example/x.png",
  );
});

it("falls back to the initial instead of a blank square", () => {
  render(<Thumb src={null} name="Roblox" />);
  expect(screen.getByText("R")).toBeInTheDocument();
});

it("falls back when the URL is there but does not load", () => {
  // A `src` that exists is not a picture that loads; the CDN has been pruned
  // before, and a 404 looks exactly like a layout hole.
  render(<Thumb src="https://cdn.example/gone.png" name="Steam" />);
  fireEvent.error(screen.getByRole("presentation", { hidden: true }));
  expect(screen.getByText("S")).toBeInTheDocument();
});

it("hides itself from screen readers — the name is right beside it", () => {
  const { container } = render(<Thumb src="https://cdn.example/x.png" name="Roblox" />);
  expect(container.firstElementChild).toHaveAttribute("aria-hidden", "true");
});

it("retries the picture when the row is re-rendered with a different one", () => {
  // Search filters the list in place, so the same component instance gets a
  // new image; a previous failure must not suppress it.
  const { rerender, container } = render(<Thumb src="https://cdn.example/gone.png" name="Steam" />);
  fireEvent.error(screen.getByRole("presentation", { hidden: true }));
  expect(screen.getByText("S")).toBeInTheDocument();

  rerender(<Thumb src="https://cdn.example/ok.png" name="Steam" />);
  expect(container.querySelector("img")).toHaveAttribute("src", "https://cdn.example/ok.png");
});
