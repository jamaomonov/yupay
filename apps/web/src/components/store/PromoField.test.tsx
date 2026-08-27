// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { PromoField } from "./PromoField";

/**
 * The partner promo field.
 *
 * Two properties are worth more than the rest. Every rejection reason gets its
 * own sentence — a single "invalid code" would leave a buyer retyping one that
 * can never work — and nothing this component does may throw, because it sits
 * inside checkout and a broken promo box must not be able to stop a sale.
 *
 * Keys are rendered verbatim by the `next-intl` mock, so an assertion on
 * `promoErrOwnCode` is an assertion that the right branch ran.
 */

vi.mock("next-intl", () => ({
  useTranslations: () => (k: string, values?: Record<string, unknown>) =>
    values ? `${k}:${JSON.stringify(values)}` : k,
}));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const ITEMS = [{ sku_id: "sku-1", qty: 1 }];

function stubPreview(body: unknown, ok = true): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(() =>
    Promise.resolve({
      ok,
      status: ok ? 200 : 500,
      json: () => Promise.resolve(body),
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderField(props: Partial<React.ComponentProps<typeof PromoField>> = {}): {
  onChange: ReturnType<typeof vi.fn>;
} {
  const onChange = vi.fn();
  render(
    <PromoField
      locale="ru"
      items={ITEMS}
      currency="UZS"
      isLoggedIn
      onChange={onChange}
      {...props}
    />,
  );
  return { onChange };
}

function apply(code: string): void {
  fireEvent.change(screen.getByLabelText("promoLabel"), { target: { value: code } });
  fireEvent.click(screen.getByRole("button", { name: "promoApply" }));
}

it("shows the percent, the struck-through total and the new one", async () => {
  stubPreview({
    applicable: true,
    code: "PARTNER10",
    percent: "10",
    currency: "UZS",
    total_before: "1250000",
    total_after: "1125000",
    discount: "125000",
  });
  const { onChange } = renderField();

  apply("partner10");

  await waitFor(() => {
    expect(screen.getByText('promoApplied:{"percent":"10"}')).toBeInTheDocument();
  });
  // The old price must be struck through, not merely mentioned: that is the
  // whole visual point of showing both.
  const before = screen.getByTestId("promo-total-before");
  expect(before).toHaveTextContent("1 250 000");
  expect(before.tagName.toLowerCase()).toBe("s");
  expect(screen.getByTestId("promo-total-after")).toHaveTextContent("1 125 000");

  expect(onChange).toHaveBeenCalledWith({
    code: "PARTNER10",
    percent: "10",
    totalBefore: "1250000",
    totalAfter: "1125000",
    discount: "125000",
  });
});

it.each([
  ["unknown", "promoErrUnknown"],
  ["already_used", "promoErrAlreadyUsed"],
  ["not_first_order", "promoErrNotFirstOrder"],
  ["own_code", "promoErrOwnCode"],
  ["pending_coded_order", "promoErrPending"],
])("explains the %s rejection in its own words", async (reason, message) => {
  stubPreview({
    applicable: false,
    reason,
    currency: "UZS",
    total_before: "1250000",
    total_after: "1250000",
    discount: "0",
  });
  const { onChange } = renderField();

  apply("NOPE");

  await waitFor(() => {
    expect(screen.getByText(message)).toBeInTheDocument();
  });
  expect(onChange).toHaveBeenCalledWith(null);
});

it("falls back to the generic message for a reason it does not know", async () => {
  // A reason added on the server before this component learns about it must
  // read as "could not check", not as an empty box.
  stubPreview({
    applicable: false,
    reason: "some_future_reason",
    currency: "UZS",
    total_before: "1250000",
    total_after: "1250000",
    discount: "0",
  });
  renderField();

  apply("NOPE");

  await waitFor(() => {
    expect(screen.getByText("promoErrGeneric")).toBeInTheDocument();
  });
});

it("survives a failed request instead of breaking the checkout around it", async () => {
  stubPreview({}, false);
  const { onChange } = renderField();

  apply("ANY");

  await waitFor(() => {
    expect(screen.getByText("promoErrGeneric")).toBeInTheDocument();
  });
  expect(onChange).toHaveBeenCalledWith(null);
});

it("invites a guest to sign in rather than offering a field that cannot work", () => {
  const fetchMock = stubPreview({});
  renderField({ isLoggedIn: false });

  expect(screen.getByText("promoSignIn")).toBeInTheDocument();
  expect(screen.queryByLabelText("promoLabel")).not.toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalled();
});

it("clears the applied code when it is removed", async () => {
  stubPreview({
    applicable: true,
    code: "PARTNER10",
    percent: "10",
    currency: "UZS",
    total_before: "1250000",
    total_after: "1125000",
    discount: "125000",
  });
  const { onChange } = renderField();

  apply("PARTNER10");
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "promoRemove" })).toBeInTheDocument();
  });

  fireEvent.click(screen.getByRole("button", { name: "promoRemove" }));

  expect(onChange).toHaveBeenLastCalledWith(null);
  expect(screen.getByLabelText("promoLabel")).toBeInTheDocument();
});

it("does not fire a request for an empty code", () => {
  const fetchMock = stubPreview({});
  renderField();

  expect(screen.getByRole("button", { name: "promoApply" })).toBeDisabled();
  expect(fetchMock).not.toHaveBeenCalled();
});
