// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, expect, it, vi } from "vitest";

import { GuestReviewPanel } from "./GuestReviewPanel";

import * as reviews from "@/lib/reviews";

const messages = {
  web: {
    brandReviews: {
      askTitle: "Как прошла выдача?",
      askHint: "Нажмите звёзды",
      formTitle: "Ваш отзыв",
      ratingLabel: "Оценка",
      commentLabel: "Комментарий",
      submit: "Отправить",
      submitting: "…",
      thanks: "Спасибо!",
      alreadyReviewed: "Уже оценено",
      error: "Ошибка",
    },
  },
};

afterEach(() => vi.restoreAllMocks());

function wrap(ui: React.ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <NextIntlClientProvider locale="ru" messages={messages}>
        {ui}
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

it("renders the form when eligible and not yet reviewed", async () => {
  vi.spyOn(reviews, "getReviewEligibility").mockResolvedValue({
    brand_slug: "steam",
    delivered: true,
    already_reviewed: false,
  });
  wrap(<GuestReviewPanel orderId="o1" email="g@x.com" />);
  await waitFor(() => expect(screen.getByText("Как прошла выдача?")).toBeInTheDocument());
});

it("renders nothing when already reviewed", async () => {
  vi.spyOn(reviews, "getReviewEligibility").mockResolvedValue({
    brand_slug: "steam",
    delivered: true,
    already_reviewed: true,
  });
  const { container } = wrap(<GuestReviewPanel orderId="o1" email="g@x.com" />);
  await waitFor(() => expect(container).toBeEmptyDOMElement());
});
