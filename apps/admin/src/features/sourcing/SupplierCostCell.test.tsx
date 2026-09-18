import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { SupplierCell } from "./SupplierCostCell";

import type { SourcingBrandSupplierOut } from "./types";

function renderCell(supplier: SourcingBrandSupplierOut) {
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
            isCheapest={false}
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
  });

  expect(screen.getByText("цена не снята")).toBeInTheDocument();
  expect(screen.queryByText("текущая цена SKU")).not.toBeInTheDocument();
});

it("still treats a current cost as an ordinary candidate for the cheapest badge", () => {
  renderCell({
    supplier_slug: "g2b",
    has_active_mapping: true,
    latest_cost_usdt: "1.23",
    captured_at: null,
    cost_source: "current",
  });
  // `isCheapest` is passed by the caller (BrandSourcingTable), not derived
  // here — this test only guards that a "current" cost still renders as a
  // plain switchable value (no special badge of its own competing for the
  // "дешевле всех" slot).
  expect(screen.queryByText("дешевле всех")).not.toBeInTheDocument();
});
