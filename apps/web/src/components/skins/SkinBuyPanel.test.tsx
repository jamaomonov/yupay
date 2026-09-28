// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SkinBuyPanel } from "./SkinBuyPanel";
import { SkinOffersProvider } from "./SkinOffers";
import messages from "../../../../../packages/i18n/locales/ru/web.json";

import type * as CheckoutModule from "@/lib/skin-checkout";
import type * as SkinsModule from "@/lib/skins";

import { buySkin, SkinListingGoneError, SkinPriceChangedError } from "@/lib/skin-checkout";
import { fetchSkinListings } from "@/lib/skins";
import { useLoginModal } from "@/store/useLoginModal";

const { pushMock, useAuthMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
  useAuthMock: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({ useAuth: useAuthMock }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: pushMock }) }));
vi.mock("@/lib/skin-checkout", async (importOriginal) => ({
  ...(await importOriginal<typeof CheckoutModule>()),
  buySkin: vi.fn(),
}));
vi.mock("@/lib/skins", async (importOriginal) => ({
  ...(await importOriginal<typeof SkinsModule>()),
  fetchSkinListings: vi.fn(),
}));
// The field and the picker have their own tests; here they just report ready.
vi.mock("./SkinTradeLinkField", async () => {
  const { useEffect } = await import("react");
  return {
    SkinTradeLinkField: ({
      onChange,
    }: {
      onChange: (s: { url: string; usable: boolean }) => void;
    }) => {
      useEffect(() => {
        onChange({
          url: "https://steamcommunity.com/tradeoffer/new/?partner=1&token=abcdefgh",
          usable: true,
        });
      }, [onChange]);
      return null;
    },
  };
});
vi.mock("./SkinPaymentPicker", async () => {
  const { useEffect } = await import("react");
  return {
    SkinPaymentPicker: ({
      onChange,
    }: {
      onChange: (s: { provider: string; ready: boolean }) => void;
    }) => {
      useEffect(() => {
        onChange({ provider: "click", ready: true });
      }, [onChange]);
      return null;
    },
  };
});

const offer = (id: number, usd: string, uzs: string) => ({
  listing_id: id,
  price_usd: usd,
  price_uzs: uzs,
  float_value: 0.2,
  paint_seed: 1,
  stickers: [],
  inspect_url: null,
});

function panel() {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      <SkinOffersProvider slug="ak">
        <SkinBuyPanel skuId="sku-1" slug="ak" locale="ru" />
      </SkinOffersProvider>
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  pushMock.mockReset();
  vi.mocked(buySkin).mockReset();
  vi.mocked(fetchSkinListings).mockResolvedValue({
    degraded: false,
    items: [offer(2, "31.00", "393700"), offer(1, "30.00", "381000")],
  });
  useLoginModal.setState({ isOpen: false });
});

describe("SkinBuyPanel", () => {
  it("asks a guest to sign in instead of buying", async () => {
    useAuthMock.mockReturnValue({ user: null, isLoading: false });
    panel();
    fireEvent.click(await screen.findByRole("button", { name: "Войдите, чтобы купить" }));
    expect(useLoginModal.getState().isOpen).toBe(true);
    expect(buySkin).not.toHaveBeenCalled();
  });

  it("buys the cheapest offer and goes to the order", async () => {
    useAuthMock.mockReturnValue({ user: { id: "u1" }, isLoading: false });
    vi.mocked(buySkin).mockResolvedValue({
      orderId: "o1",
      intentUrl: null,
      trackHref: "/orders/o1",
    });
    panel();
    fireEvent.click(await screen.findByRole("button", { name: /Оплатить 381\s?000/ }));
    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/orders/o1");
    });
    expect(vi.mocked(buySkin).mock.calls[0]![0]).toMatchObject({
      listingId: 1,
      amountUsd: "30.00",
      provider: "click",
    });
  });

  it("shows a moved price instead of charging it", async () => {
    useAuthMock.mockReturnValue({ user: { id: "u1" }, isLoading: false });
    vi.mocked(buySkin).mockRejectedValue(new SkinPriceChangedError("31.50"));
    panel();
    fireEvent.click(await screen.findByRole("button", { name: /Оплатить/ }));
    expect(await screen.findByText(/Цена изменилась/)).toBeInTheDocument();
  });

  it("moves to the next offer when the chosen one is sold", async () => {
    useAuthMock.mockReturnValue({ user: { id: "u1" }, isLoading: false });
    vi.mocked(buySkin).mockRejectedValueOnce(
      new SkinListingGoneError({ listing_id: 2, price_usd: "31.00" }),
    );
    panel();
    fireEvent.click(await screen.findByRole("button", { name: /Оплатить 381\s?000/ }));
    expect(await screen.findByText(/Этот лот уже купили/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Оплатить 393\s?700/ })).toBeInTheDocument();
  });
});
