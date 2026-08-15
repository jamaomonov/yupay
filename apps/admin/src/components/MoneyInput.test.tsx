// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { MoneyInput } from "./MoneyInput";

const NBSP = " ";

/** Mirrors how WalletPage/PromoPage actually use it — value/onChange backed
 *  by plain component state, so a keystroke round-trips through a real
 *  re-render exactly like it would in the app. */
function Harness({ initial = "" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return <MoneyInput aria-label="Сумма" value={value} onChange={setValue} />;
}

/** Simulates one keystroke inserted at the current caret — the browser
 *  applies the edit and moves the caret before firing `input`/`change`, so
 *  the event carries the post-edit value and cursor already in place. */
function typeChar(input: HTMLInputElement, char: string): void {
  const start = input.selectionStart ?? input.value.length;
  const end = input.selectionEnd ?? start;
  const nextValue = input.value.slice(0, start) + char + input.value.slice(end);
  const nextCursor = start + char.length;
  fireEvent.change(input, {
    target: { value: nextValue, selectionStart: nextCursor, selectionEnd: nextCursor },
  });
}

describe("MoneyInput", () => {
  it("groups digits as they're typed", () => {
    render(<Harness />);
    const input = screen.getByLabelText<HTMLInputElement>("Сумма");

    for (const ch of "12000000") typeChar(input, ch);

    expect(input).toHaveValue(`12${NBSP}000${NBSP}000`);
  });

  it("keeps the value it hands back to onChange ungrouped", () => {
    let seen = "";
    function Spy() {
      const [value, setValue] = useState("");
      return (
        <MoneyInput
          aria-label="Сумма"
          value={value}
          onChange={(raw) => {
            seen = raw;
            setValue(raw);
          }}
        />
      );
    }
    render(<Spy />);
    const input = screen.getByLabelText<HTMLInputElement>("Сумма");
    for (const ch of "5000000") typeChar(input, ch);

    expect(seen).toBe("5000000");
  });

  it("shows a starting value pre-grouped", () => {
    render(<Harness initial="12000000" />);
    expect(screen.getByLabelText("Сумма")).toHaveValue(`12${NBSP}000${NBSP}000`);
  });

  it("supports a negative amount and a decimal tail", () => {
    render(<Harness />);
    const input = screen.getByLabelText<HTMLInputElement>("Сумма");

    for (const ch of "-350000.5") typeChar(input, ch);

    expect(input).toHaveValue(`-350${NBSP}000.5`);
  });

  it("lets a digit be deleted from the middle without the caret jumping to the end", () => {
    render(<Harness initial="12000000" />);
    const input = screen.getByLabelText<HTMLInputElement>("Сумма");
    expect(input).toHaveValue(`12${NBSP}000${NBSP}000`);

    // Forward-delete the "2" right after the leading "1" of "12 000 000".
    fireEvent.change(input, {
      target: { value: `1${NBSP}000${NBSP}000`, selectionStart: 1, selectionEnd: 1 },
    });

    expect(input).toHaveValue(`1${NBSP}000${NBSP}000`);
    expect(input.selectionStart).toBe(1);
  });
});
