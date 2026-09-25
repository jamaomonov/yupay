// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { ReviewAvatar } from "./ReviewAvatar";

test("shows the photo when there is one", () => {
  const { container } = render(<ReviewAvatar photoUrl="https://t.me/i/userpic/1.jpg" name="Ali" />);
  expect(container.querySelector("img")).toHaveAttribute("src", "https://t.me/i/userpic/1.jpg");
});

test("falls back to the initial without a photo", () => {
  render(<ReviewAvatar photoUrl={null} name="ali" />);
  expect(screen.getByText("A")).toBeInTheDocument();
});

test("falls back to the initial when the photo fails to load", () => {
  const { container } = render(
    <ReviewAvatar photoUrl="https://t.me/i/userpic/gone.jpg" name="Bek" />,
  );
  const img = container.querySelector("img");
  if (!img) throw new Error("expected the photo to render first");
  fireEvent.error(img);
  expect(container.querySelector("img")).toBeNull();
  expect(screen.getByText("B")).toBeInTheDocument();
});

test("treats Telegram's empty placeholder for a dead userpic as a failure", () => {
  const { container } = render(
    <ReviewAvatar photoUrl="https://t.me/i/userpic/320/x.jpg" name="Dil" />,
  );
  const img = container.querySelector("img");
  if (!img) throw new Error("expected the photo to render first");
  Object.defineProperty(img, "naturalWidth", { value: 1 });
  fireEvent.load(img);
  expect(screen.getByText("D")).toBeInTheDocument();
});

test("settles an image that already failed before hydration", () => {
  const complete = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, "complete");
  Object.defineProperty(HTMLImageElement.prototype, "complete", {
    configurable: true,
    get: () => true,
  });
  try {
    render(<ReviewAvatar photoUrl="https://t.me/i/userpic/320/y.jpg" name="Zafar" />);
    // jsdom never loads images, so naturalWidth is 0: complete + 0 = failed.
    expect(screen.getByText("Z")).toBeInTheDocument();
  } finally {
    if (complete) Object.defineProperty(HTMLImageElement.prototype, "complete", complete);
    else delete (HTMLImageElement.prototype as { complete?: boolean }).complete;
  }
});
