// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { useTelegramSignIn } from "./useTelegramSignIn";

import { useLoginModal } from "@/store/useLoginModal";
import { useToast } from "@/store/useToast";

/**
 * Telegram sign-in used to be `void loginWithTelegram(u)`: the modal stayed
 * open over a storefront that had already signed the customer in, and a
 * failure produced nothing at all.
 */

const loginWithTelegram = vi.fn<(u: Record<string, unknown>) => Promise<void>>();

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ loginWithTelegram }),
}));

const TG_USER = { id: 1, first_name: "U" };

beforeEach(() => {
  loginWithTelegram.mockReset();
  useToast.setState({ toasts: [] });
  useLoginModal.setState({ isOpen: true });
});

it("closes the modal and says so when Telegram signs the customer in", async () => {
  loginWithTelegram.mockResolvedValue(undefined);
  const { result } = renderHook(() => useTelegramSignIn());

  act(() => {
    result.current(TG_USER);
  });

  await waitFor(() => {
    expect(useLoginModal.getState().isOpen).toBe(false);
  });
  const [t] = useToast.getState().toasts;
  expect(t?.message).toBe("signedIn");
  expect(t?.tone).toBe("success");
});

it("keeps the modal open and reports the failure when sign-in fails", async () => {
  // The other methods are behind this modal — closing it on failure would
  // leave the customer signed out with nothing left on screen to retry with.
  loginWithTelegram.mockRejectedValue(new Error("nope"));
  const { result } = renderHook(() => useTelegramSignIn());

  act(() => {
    result.current(TG_USER);
  });

  await waitFor(() => {
    expect(useToast.getState().toasts).toHaveLength(1);
  });
  const [t] = useToast.getState().toasts;
  expect(t?.message).toBe("signInFailed");
  expect(t?.tone).toBe("error");
  expect(useLoginModal.getState().isOpen).toBe(true);
});
