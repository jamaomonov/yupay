// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { AboutText } from "./AboutText";

const props = {
  text: "Длинный текст об услуге.",
  moreLabel: "Читать далее",
  lessLabel: "Свернуть",
};

test("renders the copy and starts collapsed", () => {
  render(<AboutText {...props} />);
  expect(screen.getByText(props.text)).toBeInTheDocument();
  const btn = screen.getByRole("button", { name: "Читать далее" });
  expect(btn).toHaveAttribute("aria-expanded", "false");
});

test("toggles between more and less", () => {
  render(<AboutText {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Читать далее" }));
  const btn = screen.getByRole("button", { name: "Свернуть" });
  expect(btn).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(btn);
  expect(screen.getByRole("button", { name: "Читать далее" })).toBeInTheDocument();
});
