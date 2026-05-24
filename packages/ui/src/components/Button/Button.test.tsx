import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button } from "./Button";

describe("Button", () => {
  it("renders its children", () => {
    render(<Button>Click me</Button>);
    expect(screen.getByRole("button", { name: "Click me" })).toBeInTheDocument();
  });

  it("applies the primary variant by default", () => {
    render(<Button>Primary</Button>);
    const btn = screen.getByRole("button");
    // Primary button is painted with the semantic ``--accent`` token
    // (Dim Slate palette). Used to reference the legacy
    // ``--color-brand`` alias which has since been retired.
    expect(btn.className).toContain("bg-[var(--accent)]");
  });
});
