/**
 * A long name must not be able to stretch the table it sits in.
 *
 * `truncate` was on the name span from the start and did nothing: a
 * `table-auto` column grows to fit its widest cell, so there was no width to
 * truncate against. One account with a 64-character name pushed the orders
 * table to roughly four times the viewport and shoved every other column —
 * status, amount, date — off the right edge.
 *
 * Measured on a standalone reproduction of the real markup: 4269px of table
 * inside a 1066px container before the cap, 1066px after it.
 *
 * The cap is a width rather than a character count on purpose. The longest
 * names in production are 64 characters of cuneiform (`𒐫`) and Syloti Nagri,
 * glyphs several times wider than Latin at the same font size — so a
 * character limit generous enough for Latin would still overflow on these,
 * and one tight enough for these would mangle ordinary names.
 */

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { UserRef } from "./UserRef";

const LONG_NAME = `${"𒐫".repeat(34)}🇺🇿 ${"𒐫".repeat(27)}`;
const USER_ID = "019fe85d-ad61-7482-8db2-056852e74d46";

function renderRef(props: Partial<Parameters<typeof UserRef>[0]> = {}) {
  return render(
    <MemoryRouter>
      <UserRef id={USER_ID} data={{ id: USER_ID, name: LONG_NAME, photo_url: null }} {...props} />
    </MemoryRouter>,
  );
}

describe("UserRef", () => {
  it("caps the name so it cannot widen its column", () => {
    renderRef();

    const name = screen.getByText(LONG_NAME);
    expect(name.className).toContain("truncate");
    expect(name.className).toContain("max-w-[220px]");
  });

  it("keeps the whole name reachable on hover, so the cap hides nothing", () => {
    renderRef();

    // The cap is cosmetic: an operator who needs the full name still has it.
    expect(screen.getByRole("link")).toHaveAttribute("title", LONG_NAME);
  });

  it("lets a surface with room opt out", () => {
    renderRef({ nameClassName: "max-w-none" });

    const name = screen.getByText(LONG_NAME);
    expect(name.className).toContain("max-w-none");
    expect(name.className).not.toContain("max-w-[220px]");
  });

  it("still shows a shortened id when the account resolved to nothing", () => {
    // Unchanged by the cap — a deleted account keeps its row actionable.
    renderRef({ data: undefined });

    expect(screen.getByText("019fe85d…")).toBeInTheDocument();
  });
});
