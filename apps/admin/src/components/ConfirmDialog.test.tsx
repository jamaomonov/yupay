// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { expect, it } from "vitest";

import { ConfirmDialog } from "./ConfirmDialog";

/** The settle dialog's shape: a controlled input inside, parent re-renders per key. */
function WithInput() {
  const [value, setValue] = useState("");
  return (
    <ConfirmDialog
      title="t"
      confirmLabel="ok"
      onConfirm={() => undefined}
      onCancel={() => undefined}
    >
      <input
        aria-label="ref"
        value={value}
        onChange={(e) => {
          setValue(e.target.value);
        }}
      />
    </ConfirmDialog>
  );
}

it("keeps focus in an input while the operator types", async () => {
  render(<WithInput />);
  // Let the initial focus (the confirm button) land first.
  await act(async () => {
    await new Promise((r) => setTimeout(r, 10));
  });

  const input = screen.getByLabelText("ref");
  input.focus();
  fireEvent.change(input, { target: { value: "C" } });
  fireEvent.change(input, { target: { value: "CL" } });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 10));
  });

  expect(input).toHaveFocus();
  expect(input).toHaveValue("CL");
});
