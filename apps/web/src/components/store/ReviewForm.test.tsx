// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { ReviewForm } from "./ReviewForm";

vi.mock("next-intl", () => ({
  useTranslations: () => (k: string) => k,
}));

test("offers no canned phrases; Submit sends what the buyer typed", async () => {
  const onAmend = vi.fn<(body: string) => Promise<void>>();
  onAmend.mockResolvedValue(undefined);

  render(
    <ReviewForm
      onSubmit={() => undefined}
      onAmend={onAmend}
      submitting={false}
      showError={false}
      rated={5}
    />,
  );

  // Removed 2026-09-25: one-tap phrases made every review read the same.
  expect(screen.queryByRole("button", { name: /^tag/ })).not.toBeInTheDocument();

  fireEvent.change(screen.getByRole("textbox"), { target: { value: "всё пришло за минуту" } });
  expect(onAmend).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "submit" }));

  await waitFor(() => {
    expect(onAmend).toHaveBeenCalledTimes(1);
  });
  expect(onAmend).toHaveBeenCalledWith("всё пришло за минуту");
});

test("skip leaves the body empty and still shows the thank-you", async () => {
  const onAmend = vi.fn();
  render(
    <ReviewForm
      onSubmit={() => undefined}
      onAmend={onAmend}
      submitting={false}
      showError={false}
      rated={5}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "skipComment" }));

  expect(onAmend).not.toHaveBeenCalled();
  expect(await screen.findByText("thanks")).toBeInTheDocument();
  expect(screen.getByText("thanksBody")).toBeInTheDocument();
});

test("a star tap only selects; Submit sends the stars last tapped", () => {
  const onSubmit = vi.fn<(rating: number) => void>();
  render(<ReviewForm onSubmit={onSubmit} submitting={false} showError={false} />);

  expect(screen.queryByRole("button", { name: "submit" })).not.toBeInTheDocument();
  // A thumb landing on the first star on the way to the fifth (2026-10-13).
  fireEvent.click(screen.getByRole("button", { name: "1" }));
  fireEvent.click(screen.getByRole("button", { name: "5" }));
  expect(onSubmit).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "submit" }));
  expect(onSubmit).toHaveBeenCalledTimes(1);
  expect(onSubmit).toHaveBeenCalledWith(5);
});
