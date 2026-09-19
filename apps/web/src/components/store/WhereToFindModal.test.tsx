// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { WhereToFindModal, type WhereToFindImage } from "./WhereToFindModal";

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

test("a field with text and no images still renders the text and nothing else breaks", () => {
  render(<WhereToFindModal open onClose={vi.fn()} {...props} images={null} />);
  expect(screen.getByText(/Строка 1/)).toBeInTheDocument();
  expect(screen.queryAllByRole("img")).toHaveLength(0);
});

test("renders images in order with their captions", () => {
  const images: WhereToFindImage[] = [
    {
      url: "https://cdn.yupay.uz/help/1.png",
      alt: "Откройте профиль",
      caption: "Откройте профиль",
    },
    { url: "https://cdn.yupay.uz/help/2.png", alt: "ID под ником", caption: "ID под ником" },
  ];
  render(<WhereToFindModal open onClose={vi.fn()} {...props} images={images} />);

  // A visible caption already says what the step is; the alt goes empty
  // rather than repeat it (a screen reader would otherwise hear it twice) —
  // which per ARIA makes the image presentational, not `role="img"` (same
  // as the admin's own thumbnails; see Thumb.test.tsx).
  const rendered = screen.getAllByRole("presentation", { hidden: true });
  expect(rendered).toHaveLength(2);
  expect(rendered[0]).toHaveAttribute("src", expect.stringContaining("1.png"));
  expect(rendered[1]).toHaveAttribute("src", expect.stringContaining("2.png"));
  expect(rendered[0]).toHaveAttribute("alt", "");
  expect(rendered[1]).toHaveAttribute("alt", "");
  // The caption sits with its image, not just in the alt.
  expect(screen.getByText("Откройте профиль")).toBeInTheDocument();
  expect(screen.getByText("ID под ником")).toBeInTheDocument();
});

test("an image with no caption still gets a non-empty alt", () => {
  const images: WhereToFindImage[] = [
    { url: "https://cdn.yupay.uz/help/1.png", alt: "Шаг 1 из 1", caption: null },
  ];
  render(<WhereToFindModal open onClose={vi.fn()} {...props} images={images} />);

  const img = screen.getByRole("img");
  expect(img).toHaveAttribute("alt", "Шаг 1 из 1");
  expect(img.getAttribute("alt")).not.toBe("");
});

test("a longer-than-expected image list still renders without breaking", () => {
  const images: WhereToFindImage[] = Array.from({ length: 12 }, (_, i) => ({
    url: `https://cdn.yupay.uz/help/${String(i)}.png`,
    alt: `Шаг ${String(i + 1)}`,
    caption: null,
  }));
  render(<WhereToFindModal open onClose={vi.fn()} {...props} images={images} />);
  const rendered = screen.getAllByRole("img");
  expect(rendered).toHaveLength(12);

  // jsdom has no layout engine, so this cannot prove the close button stays
  // *visually* on screen at a given scroll position — only a real browser
  // (Playwright) can. What it can prove is the fix's actual mechanism: all
  // 12 images live inside the one scrolling body container, while the close
  // button is not a descendant of that container — an absolutely-positioned
  // child of a scroll container scrolls away with its content, so keeping
  // the button outside it is what stops that happening.
  const dialog = screen.getByRole("dialog");
  const scrollArea = dialog.querySelector(".overflow-y-auto");
  expect(scrollArea).not.toBeNull();
  expect(scrollArea?.querySelectorAll("img")).toHaveLength(12);

  const closeButton = screen.getByRole("button", { name: "Закрыть" });
  expect(closeButton).toBeInTheDocument();
  expect(closeButton.closest(".overflow-y-auto")).toBeNull();
});
