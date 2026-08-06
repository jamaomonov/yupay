import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Select } from "./Select";

describe("Select", () => {
  it("stays a real select — options, value and change events all work", () => {
    const onChange = vi.fn();
    render(
      <Select aria-label="Статус" value="paid" onChange={onChange}>
        <option value="paid">Оплачен</option>
        <option value="delivered">Доставлен</option>
      </Select>,
    );

    const select = screen.getByRole("combobox", { name: "Статус" });
    expect(select).toHaveValue("paid");
    fireEvent.change(select, { target: { value: "delivered" } });
    expect(onChange).toHaveBeenCalled();
  });

  it("carries a focus ring, which the hand-rolled selects it replaces did not", () => {
    render(<Select aria-label="Фильтр" />);
    expect(screen.getByRole("combobox").className).toContain("focus-visible:ring-2");
  });

  it("hides the decorative chevron from assistive tech", () => {
    const { container } = render(<Select aria-label="Фильтр" />);
    // The native arrow is suppressed via appearance-none, so the replacement
    // must not read out as an extra element.
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });
});
