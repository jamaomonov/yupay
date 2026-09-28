// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { expect, it } from "vitest";

import { numberCodec, useSearchParamsState } from "./useSearchParamsState";

function Probe() {
  const [, setStatus] = useSearchParamsState("status", "");
  const [, setOffset] = useSearchParamsState("offset", 0, numberCodec);
  const location = useLocation();
  return (
    <>
      <button
        type="button"
        onClick={() => {
          // A filter change and a page reset in one handler — the pattern list pages use.
          setStatus("failed");
          setOffset(0);
        }}
      >
        filter
      </button>
      <output>{location.search}</output>
    </>
  );
}

it("composes two setters fired in one handler", () => {
  render(
    <MemoryRouter initialEntries={["/orders?offset=50"]}>
      <Probe />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByRole("button", { name: "filter" }));
  expect(screen.getByRole("status")).toHaveTextContent("?status=failed");
});
