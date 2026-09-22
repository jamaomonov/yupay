import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { SupplierCell } from "./SupplierCostCell";

import type { SourcingBrandSupplierOut } from "./types";

// `isCheapest` is overridable (default false, matching every existing
// case below that doesn't care about the badge) so a test that specifically
// exercises the badge can actually flip it — rendering with a value
// hardcoded to `false` would let a `queryByText("дешевле всех")` assertion
// pass regardless of what the component does with a `true` value, which is
// worse than no test at all (whole-branch review #1).
function renderCell(supplier: SourcingBrandSupplierOut, isCheapest = false) {
  return render(
    <table>
      <tbody>
        <tr>
          <SupplierCell
            slug="g2b"
            supplier={supplier}
            isCurrentRoute={false}
            isFallbackRoute={false}
            wouldBypassInventory={false}
            isCheapest={isCheapest}
            pending={false}
            onSwitch={vi.fn()}
          />
        </tr>
      </tbody>
    </table>,
  );
}

it("renders a captured history price with its capture date, unchanged", () => {
  renderCell({
    supplier_slug: "g2b",
    has_active_mapping: true,
    latest_cost_usdt: "0.90",
    captured_at: "2026-09-10T00:00:00Z",
    cost_source: "history",
    stock: null,
    stock_at: null,
  });

  expect(screen.getByTitle("0.90 USDT")).toBeInTheDocument();
  expect(screen.getByText("10.09.26")).toBeInTheDocument();
  expect(screen.queryByText("текущая цена SKU")).not.toBeInTheDocument();
});

it('marks a cost with no history row as the SKU\'s current cost, not "цена не снята" — the g2b/Free Fire gap', () => {
  renderCell({
    supplier_slug: "g2b",
    has_active_mapping: true,
    latest_cost_usdt: "1.23",
    captured_at: null,
    cost_source: "current",
    stock: null,
    stock_at: null,
  });

  expect(screen.getByText(/1,23/)).toBeInTheDocument();
  expect(screen.getByText("текущая цена SKU")).toBeInTheDocument();
  expect(screen.queryByText("цена не снята")).not.toBeInTheDocument();
});

it('still renders "цена не снята" when the cost is genuinely unknown', () => {
  renderCell({
    supplier_slug: "g2b",
    has_active_mapping: true,
    latest_cost_usdt: null,
    captured_at: null,
    cost_source: null,
    stock: null,
    stock_at: null,
  });

  expect(screen.getByText("цена не снята")).toBeInTheDocument();
  expect(screen.queryByText("текущая цена SKU")).not.toBeInTheDocument();
});

it('renders "цена не снята" and no "текущая цена SKU" note for the cost_source="current" + null-cost combination the backend is being fixed to stop producing — the cell must not claim a current price it is not showing', () => {
  renderCell({
    supplier_slug: "g2b",
    has_active_mapping: true,
    latest_cost_usdt: null,
    captured_at: null,
    cost_source: "current",
    stock: null,
    stock_at: null,
  });

  expect(screen.getByText("цена не снята")).toBeInTheDocument();
  // "текущая цена SKU" annotates a displayed value as coming straight from
  // Sku.cost_usdt rather than a captured history row. With no value
  // displayed at all, that note would sit right under "цена не снята" and
  // read as claiming a price the cell isn't showing.
  expect(screen.queryByText("текущая цена SKU")).not.toBeInTheDocument();
});

it("shows the cheapest badge for a current cost when the caller says it is cheapest", () => {
  renderCell(
    {
      supplier_slug: "g2b",
      has_active_mapping: true,
      latest_cost_usdt: "1.23",
      captured_at: null,
      cost_source: "current",
      stock: null,
      stock_at: null,
    },
    true,
  );
  // `isCheapest` is passed by the caller (BrandSourcingTable), not derived
  // here — this checks the cell actually honours a `true` value for a
  // "current" cost, not just that it stays quiet when passed `false`
  // (which the next test covers, and which every other test above already
  // exercised by never passing `true` at all).
  expect(screen.getByText("дешевле всех")).toBeInTheDocument();
});

it("shows no cheapest badge for a current cost when the caller says it is not cheapest", () => {
  renderCell(
    {
      supplier_slug: "g2b",
      has_active_mapping: true,
      latest_cost_usdt: "1.23",
      captured_at: null,
      cost_source: "current",
      stock: null,
      stock_at: null,
    },
    false,
  );
  // A "current" cost still renders as a plain switchable value — no
  // special badge of its own competing for the "дешевле всех" slot.
  expect(screen.queryByText("дешевле всех")).not.toBeInTheDocument();
});

it("shows this supplier's own stock, and flags an empty one", () => {
  // The whole point of the column: the supplier a SKU is pinned to can be
  // empty while another is not, and `Sku.supplier_stock` — one number, the
  // routed supplier's — cannot say so.
  renderCell({
    supplier_slug: "gengine",
    has_active_mapping: true,
    latest_cost_usdt: "4.65",
    captured_at: null,
    cost_source: "history",
    stock: 0,
    stock_at: "2026-09-22T14:51:46Z",
  });

  expect(screen.getByText("нет в наличии")).toBeInTheDocument();
});

it("renders a known count, and leaves an unknown one blank rather than zero", () => {
  const { unmount } = renderCell({
    supplier_slug: "nova",
    has_active_mapping: true,
    latest_cost_usdt: "1.41",
    captured_at: null,
    cost_source: "history",
    stock: 19,
    stock_at: "2026-09-22T14:51:55Z",
  });
  expect(screen.getByText("в наличии: 19")).toBeInTheDocument();
  unmount();

  // `null` means we never asked this supplier about this rung. Rendering it
  // as "нет в наличии" would push an operator off a supplier that can
  // actually deliver — the same mistake `normalise_stock` avoids server-side.
  renderCell({
    supplier_slug: "g2b",
    has_active_mapping: true,
    latest_cost_usdt: "1.60",
    captured_at: null,
    cost_source: "history",
    stock: null,
    stock_at: null,
  });
  expect(screen.queryByText("нет в наличии")).not.toBeInTheDocument();
  expect(screen.queryByText(/в наличии:/)).not.toBeInTheDocument();
});
