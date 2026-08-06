import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatCard } from "./StatCard";

describe("StatCard", () => {
  it("renders the figure and its label", () => {
    render(<StatCard label="Всего по фильтру" value={42} />);
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("Всего по фильтру")).toBeInTheDocument();
  });

  it("dims a muted figure — the state the old copies rendered as normal", () => {
    const { container } = render(<StatCard label="Ждут оплаты" value={0} tone="muted" />);
    expect(container.querySelector(".text-\\[var\\(--text-secondary\\)\\]")).not.toBeNull();
  });

  it("keeps the accent on a headline tile even when tone says otherwise", () => {
    // Orders passes tone from a counter that can be zero; the headline tile
    // must not turn grey just because its number did.
    const { container } = render(<StatCard label="Всего" value={0} accent tone="muted" />);
    expect(container.querySelector(".text-\\[var\\(--accent\\)\\]")).not.toBeNull();
  });

  it("accepts a node so a tile can hold a sparkline", () => {
    render(<StatCard label="События" value={<svg data-testid="spark" />} />);
    expect(screen.getByTestId("spark")).toBeInTheDocument();
  });
});
