// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useOrderSocket } from "./useOrderSocket";

import type { Me } from "@/lib/auth";
import type { OrderUpdateMessage } from "@yupay/api-client";
import type { ReactNode } from "react";

let capturedHandlers: {
  onMessage: (m: OrderUpdateMessage) => void;
  onOpen?: () => void;
  onClose?: () => void;
} | null = null;
const mockConnect = vi.fn();
const mockClose = vi.fn();

vi.mock("@yupay/api-client", () => ({
  OrderSocket: vi.fn().mockImplementation((opts: typeof capturedHandlers) => {
    capturedHandlers = opts;
    return { connect: mockConnect, close: mockClose };
  }),
}));

const MOCK_USER: Me = {
  id: "user-1",
  email: "buyer@example.com",
  locale: "ru",
  display_currency: "USD",
  display_name: null,
  photo_url: null,
  roles: [],
  created_at: "2026-07-01T00:00:00Z",
};

let mockAuthUser: Me | null = MOCK_USER;

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: mockAuthUser }),
}));

import { useOrderDeliveredModal } from "@/store/useOrderDeliveredModal";
import { useRealtimeStatus } from "@/store/useRealtimeStatus";

function renderWithClient(client: QueryClient) {
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return renderHook(
    () => {
      useOrderSocket();
    },
    { wrapper },
  );
}

beforeEach(() => {
  capturedHandlers = null;
  mockConnect.mockClear();
  mockClose.mockClear();
  mockAuthUser = MOCK_USER;
  useRealtimeStatus.setState({ connected: false });
  useOrderDeliveredModal.setState({ orderId: null });
});

describe("useOrderSocket", () => {
  it("connects one OrderSocket for a logged-in user", () => {
    const qc = new QueryClient();
    renderWithClient(qc);
    expect(mockConnect).toHaveBeenCalledTimes(1);
    expect(capturedHandlers).not.toBeNull();
  });

  it("does not connect for a guest", () => {
    mockAuthUser = null;
    const qc = new QueryClient();
    renderWithClient(qc);
    expect(mockConnect).not.toHaveBeenCalled();
    expect(capturedHandlers).toBeNull();
  });

  it("invalidates the order query on order.status_changed", () => {
    const qc = new QueryClient();
    const invalidateSpy = vi.spyOn(qc, "invalidateQueries");
    renderWithClient(qc);

    act(() => {
      capturedHandlers?.onMessage({
        type: "order.status_changed",
        orderId: "order-abc",
        status: "paid",
        at: "2026-07-28T00:00:00Z",
      });
    });

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["order", "order-abc"] });
  });

  it("invalidates the order query and opens the delivered modal on order.delivered", () => {
    const qc = new QueryClient();
    const invalidateSpy = vi.spyOn(qc, "invalidateQueries");
    renderWithClient(qc);

    act(() => {
      capturedHandlers?.onMessage({
        type: "order.delivered",
        orderId: "order-xyz",
        payload: { kind: "code", data: {} },
      });
    });

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["order", "order-xyz"] });
    expect(useOrderDeliveredModal.getState().orderId).toBe("order-xyz");
  });

  it("ignores ping and order.failed messages", () => {
    const qc = new QueryClient();
    const invalidateSpy = vi.spyOn(qc, "invalidateQueries");
    renderWithClient(qc);

    act(() => {
      capturedHandlers?.onMessage({ type: "ping", at: "2026-07-28T00:00:00Z" });
      capturedHandlers?.onMessage({
        type: "order.failed",
        orderId: "order-nope",
        reason: "supplier_error",
      });
    });

    expect(invalidateSpy).not.toHaveBeenCalled();
    expect(useOrderDeliveredModal.getState().orderId).toBeNull();
  });

  it("toggles useRealtimeStatus().connected on open/close", () => {
    const qc = new QueryClient();
    renderWithClient(qc);

    act(() => {
      capturedHandlers?.onOpen?.();
    });
    expect(useRealtimeStatus.getState().connected).toBe(true);

    act(() => {
      capturedHandlers?.onClose?.();
    });
    expect(useRealtimeStatus.getState().connected).toBe(false);
  });

  it("closes the socket and clears connected state on unmount", () => {
    const qc = new QueryClient();
    const { unmount } = renderWithClient(qc);

    act(() => {
      capturedHandlers?.onOpen?.();
    });
    expect(useRealtimeStatus.getState().connected).toBe(true);

    unmount();

    expect(mockClose).toHaveBeenCalledTimes(1);
    expect(useRealtimeStatus.getState().connected).toBe(false);
  });
});
