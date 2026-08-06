import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CopyId } from "./CopyId";

const FULL = "019f6b60-0000-7000-8000-0000000000bb";

describe("CopyId", () => {
  it("shows a truncated id but copies the whole thing", async () => {
    const writeText = vi.fn<(text: string) => Promise<void>>().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    render(<CopyId value={FULL} />);
    const button = screen.getByRole("button");
    expect(button).toHaveTextContent("019f6b60…");
    // The full value stays reachable without a copy — tooltip and label both
    // carry it, which is what makes this usable in a screen reader too.
    expect(button).toHaveAttribute("title", expect.stringContaining(FULL));

    fireEvent.click(button);
    expect(writeText).toHaveBeenCalledWith(FULL);
    await waitFor(() => {
      expect(screen.getByText("Скопировано")).toBeInTheDocument();
    });
  });

  it("does not trigger the surrounding row's click handler", () => {
    vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    // These chips sit inside rows that navigate on click; copying an id must
    // not also yank the operator off the list they are working through.
    const onRowClick = vi.fn();

    render(
      <div onClick={onRowClick}>
        <CopyId value={FULL} />
      </div>,
    );
    fireEvent.click(screen.getByRole("button"));

    expect(onRowClick).not.toHaveBeenCalled();
  });

  it("reports failure instead of pretending it copied", async () => {
    // No clipboard API (insecure context) and a refused execCommand fallback.
    // `execCommand` is defined rather than spied on: jsdom doesn't implement
    // it, so there is no property for vi.spyOn to wrap.
    vi.stubGlobal("navigator", { clipboard: undefined });
    Object.defineProperty(document, "execCommand", {
      value: vi.fn().mockReturnValue(false),
      configurable: true,
    });

    render(<CopyId value={FULL} />);
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => {
      expect(screen.getByText("Скопировать не удалось")).toBeInTheDocument();
    });
  });

  it("leaves a short value alone", () => {
    vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    render(<CopyId value="abc" />);
    expect(screen.getByRole("button")).toHaveTextContent("abc");
    expect(screen.getByRole("button")).not.toHaveTextContent("…");
  });
});
