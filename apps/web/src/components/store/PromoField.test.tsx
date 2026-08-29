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
  rerender: (next: Partial<React.ComponentProps<typeof PromoField>>) => void;
  unmount: () => void;
} {
  const onChange = vi.fn();
  const element = (
    overrides: Partial<React.ComponentProps<typeof PromoField>>,
  ): React.ReactElement => (
    <PromoField
      locale="ru"
      items={ITEMS}
      currency="UZS"
      isLoggedIn
      onChange={onChange}
      {...props}
      {...overrides}
    />
  );
  const view = render(element({}));
  return {
    onChange,
    rerender: (next) => {
      view.rerender(element(next));
    },
    unmount: view.unmount,
  };
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

/**
 * What happens when the cart changes underneath an applied code.
 *
 * The field priced the cart once, on apply, and kept the answer. A buyer who
 * then switched packages was shown the previous package's discounted total —
 * and the host puts that number on its pay button, so checkout quoted a price
 * that was never going to be charged. These are the tests for that.
 */

const CHEAP = [{ sku_id: "sku-1", qty: 1 }];
const DEAR = [{ sku_id: "sku-2", qty: 1 }];

/** Answers each call with the next body in the queue. */
function stubPreviewSequence(bodies: unknown[]): ReturnType<typeof vi.fn> {
  let call = 0;
  const fetchMock = vi.fn(() => {
    const body = bodies[Math.min(call, bodies.length - 1)];
    call += 1;
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const APPLIED_CHEAP = {
  applicable: true,
  code: "PARTNER10",
  percent: "10",
  currency: "UZS",
  total_before: "62081",
  total_after: "55873",
  discount: "6208",
};

const APPLIED_DEAR = {
  applicable: true,
  code: "PARTNER10",
  percent: "10",
  currency: "UZS",
  total_before: "124163",
  total_after: "111747",
  discount: "12416",
};

it("re-prices the code when the buyer switches package", async () => {
  const fetchMock = stubPreviewSequence([APPLIED_CHEAP, APPLIED_DEAR]);
  const { onChange, rerender } = renderField({ items: CHEAP });

  apply("PARTNER10");
  await waitFor(() => {
    expect(screen.getByTestId("promo-total-after")).toHaveTextContent("55 873");
  });

  rerender({ items: DEAR });

  await waitFor(
    () => {
      expect(screen.getByTestId("promo-total-after")).toHaveTextContent("111 747");
    },
    { timeout: 3000 },
  );
  expect(screen.getByTestId("promo-total-before")).toHaveTextContent("124 163");

  // The second call must carry the new cart, not the one the code was applied
  // to.
  const secondBody = JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body)) as {
    items: { sku_id: string }[];
  };
  expect(secondBody.items[0]?.sku_id).toBe("sku-2");

  expect(onChange).toHaveBeenLastCalledWith({
    code: "PARTNER10",
    percent: "10",
    totalBefore: "124163",
    totalAfter: "111747",
    discount: "12416",
  });
});

it("withdraws the discount while the new total is being fetched", async () => {
  // The gap between "the cart changed" and "the server answered" is the whole
  // bug: for as long as it lasts the host must have no discount to show, or it
  // shows the previous package's.
  stubPreviewSequence([APPLIED_CHEAP, APPLIED_DEAR]);
  const { onChange, rerender } = renderField({ items: CHEAP });

  apply("PARTNER10");
  await waitFor(() => {
    expect(screen.getByTestId("promo-total-after")).toBeInTheDocument();
  });
  onChange.mockClear();

  rerender({ items: DEAR });

  await waitFor(() => {
    expect(onChange).toHaveBeenCalledWith(null);
  });
});

it("drops the discount when the cart empties", async () => {
  stubPreviewSequence([APPLIED_CHEAP]);
  const { onChange, rerender } = renderField({ items: CHEAP });

  apply("PARTNER10");
  await waitFor(() => {
    expect(screen.getByTestId("promo-total-after")).toBeInTheDocument();
  });

  rerender({ items: [] });

  await waitFor(() => {
    expect(onChange).toHaveBeenLastCalledWith(null);
  });
  // The code stays in the box: the buyer typed it, and making them type it
  // again because they changed their mind about a package is a punishment.
  expect(screen.getByLabelText("promoLabel")).toHaveValue("PARTNER10");
});

it("offers the field before a package is chosen, but cannot apply yet", () => {
  const fetchMock = stubPreview({});
  renderField({ items: [] });

  // Visible from the start — a buyer holding a code should not have to guess
  // whether this checkout takes one.
  expect(screen.getByLabelText("promoLabel")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("promoLabel"), { target: { value: "PARTNER10" } });

  expect(screen.getByRole("button", { name: "promoApply" })).toBeDisabled();
  expect(screen.getByText("promoNeedPackage")).toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalled();
});

it("tells the host there is no discount once it leaves the tree", async () => {
  stubPreviewSequence([APPLIED_CHEAP]);
  const { onChange, unmount } = renderField({ items: CHEAP });

  apply("PARTNER10");
  await waitFor(() => {
    expect(screen.getByTestId("promo-total-after")).toBeInTheDocument();
  });

  // The Mini App unmounts this field when the buyer steps back to the package
  // picker. The discount used to survive that, invisibly, and stayed on the
  // pay button.
  unmount();

  expect(onChange).toHaveBeenLastCalledWith(null);
});
