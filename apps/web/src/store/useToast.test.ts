import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { toast, useToast } from "./useToast";

beforeEach(() => {
  vi.useFakeTimers();
  useToast.setState({ toasts: [] });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useToast", () => {
  it("queues a toast with the requested tone", () => {
    toast.success("Скопировано");
    const [t] = useToast.getState().toasts;
    expect(t?.message).toBe("Скопировано");
    expect(t?.tone).toBe("success");
  });

  it("auto-dismisses after the display window", () => {
    toast.info("hi");
    expect(useToast.getState().toasts).toHaveLength(1);
    vi.advanceTimersByTime(4_000);
    expect(useToast.getState().toasts).toHaveLength(0);
  });

  it("can be dismissed early by id", () => {
    toast.error("boom");
    const id = useToast.getState().toasts[0]?.id ?? "";
    expect(id).not.toBe("");
    useToast.getState().dismiss(id);
    expect(useToast.getState().toasts).toHaveLength(0);
  });

  it("caps the stack so a burst can't cover the viewport", () => {
    for (let i = 0; i < 6; i++) toast.info(`msg-${String(i)}`);
    const { toasts } = useToast.getState();
    expect(toasts).toHaveLength(3);
    // Keeps the newest — the oldest are the ones dropped.
    expect(toasts.at(-1)?.message).toBe("msg-5");
  });
});
