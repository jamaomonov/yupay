// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { ReviewForm } from "./ReviewForm";

vi.mock("next-intl", () => ({
  useTranslations: () => (k: string) => k,
}));

test("does not PATCH on a chip tap; Submit sends the shared draft", async () => {
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

  fireEvent.click(screen.getByRole("button", { name: "tagFast" }));
  expect(onAmend).not.toHaveBeenCalled();
  expect(screen.getByRole("textbox")).toHaveValue("tagFast");

  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "tagFast. всё пришло" },
  });
  fireEvent.click(screen.getByRole("button", { name: "submit" }));

  await waitFor(() => {
    expect(onAmend).toHaveBeenCalledTimes(1);
  });
  expect(onAmend).toHaveBeenCalledWith("tagFast. всё пришло");
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
