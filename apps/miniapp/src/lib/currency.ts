/**
 * Display currency: which fiat / USDT the catalog prices and the wallet
 * balance are shown in.
 *
 * Source of truth is the user row on the backend (``users.display_currency``).
 * We do **not** keep a parallel Zustand store anymore — the previous
 * localStorage-only version drifted between devices and never propagated to
 * the wallet, which kept showing USD regardless. The setter goes through
 * ``PATCH /api/v1/users/me`` and optimistically patches the ``/auth/me``
 * cache so the UI flips instantly.
 *
 * Affects ``useProductWithSkus`` (passes ``?currency=`` to the API) and the
 * wallet hero on the Wallet page (FX-converted via ``useFxRate``).
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiPatch } from "./api";
import { useMe, type Me } from "./auth";
import { getActiveLocale } from "./i18n/core";

export const DISPLAY_CURRENCIES = ["USD", "UZS", "RUB", "USDT"] as const;
export type DisplayCurrency = (typeof DISPLAY_CURRENCIES)[number];

export const CURRENCY_LABEL: Record<DisplayCurrency, string> = {
  USD: "Доллар США",
  UZS: "Узбекский сум",
  RUB: "Российский рубль",
  USDT: "Tether USDT",
};

export function isDisplayCurrency(value: string | undefined | null): value is DisplayCurrency {
  return value != null && (DISPLAY_CURRENCIES as readonly string[]).includes(value);
}

// ISO 4217 currencies YuPay handles that carry no practically-displayed minor
// unit — UZS technically has tiyin, but showing them just renders noisy
// ",00"/",79" suffixes on already-large sums. Mirrors packages/utils/money.ts.
const ZERO_DECIMAL_CURRENCIES = new Set(["UZS"]);

/**
 * Localized word for a UZS amount — the storefront-wide fix for `Intl`'s own
 * `style:"currency"` rendering the ISO code instead of a word: "165 000 UZS"
 * in ru (Latin letters sitting in the middle of a Cyrillic sentence), "UZS
 * 165,000" in en (the code even leads the number). Mirrors `formatUzs` in
 * `apps/web/src/lib/seo.ts` — keep the two in sync.
 */
function uzsWord(locale: string): string {
  if (locale === "ru") return "сум";
  if (locale === "uz") return "soʻm";
  return "UZS";
}

/**
 * Format a money amount in the given ISO-ish currency code, honoring the
 * active locale. Shared by every page that prints a sum price (`TopUp`,
 * the Steam Gifts catalog/game screens) so a formatting tweak lands once.
 */
export function formatMoney(value: number, code: string): string {
  const locale = getActiveLocale();
  const fractionDigits = ZERO_DECIMAL_CURRENCIES.has(code) ? 0 : 2;
  if (code === "UZS") {
    // `Intl`'s currency style is what prints the bare ISO code — build the
    // number ourselves and append the localized word instead (see `uzsWord`).
    const number = new Intl.NumberFormat(locale, {
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    }).format(value);
    return `${number} ${uzsWord(locale)}`;
  }
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency: code,
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    }).format(value);
  } catch {
    // Non-ISO pseudocurrency (USDT) — format the number, suffix the code.
    return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value)} ${code}`;
  }
}

/**
 * Currency word/symbol for the given code, honoring the active locale for
 * UZS (see `uzsWord`) — the other three are locale-invariant glyphs.
 *
 * `formatBalance` (`lib/wallet.ts`) renders the wallet tile's symbol itself
 * rather than trusting `style:"currency"` (Telegram's font sometimes mangles
 * the ₽ Intl would supply), so it calls this instead of duplicating the UZS
 * mapping — that's also what keeps the wallet tile and `formatMoney`'s price
 * agreeing on "сум"/"soʻm"/"UZS" instead of the tile alone showing the bare
 * ISO code.
 */
export function currencySymbol(code: DisplayCurrency, locale: string): string {
  if (code === "UZS") return uzsWord(locale);
  const symbols: Record<Exclude<DisplayCurrency, "UZS">, string> = {
    USD: "$",
    RUB: "₽",
    USDT: "USDT",
  };
  return symbols[code];
}

/**
 * Active display currency. Pinned to UZS while the storefront ships
 * UZ-only — selector in Settings is hidden, and even legacy users with
 * ``display_currency="USD"`` see the catalog in UZS. When we localise
 * for RU / EN this will switch back to reading ``me.display_currency``
 * (or, more likely, derive from ``me.locale`` so each market gets its
 * own native currency instead of a free-form preference).
 */
export function useDisplayCurrency(): DisplayCurrency {
  // Tip: ``useMe`` is intentionally still called so the hook keeps its
  // existing dependency on auth — every page that renders prices stays
  // gated by login, and switching back to per-user currency later is a
  // one-line change.
  useMe();
  return "UZS";
}

/**
 * Mutation that flips the user's display currency. Optimistically patches
 * the ``/auth/me`` cache so the whole UI updates in the same frame the user
 * taps an option, then awaits the PATCH and invalidates wallet/catalog
 * queries (their result shapes depend on the chosen currency).
 */
export function useUpdateDisplayCurrency() {
  const qc = useQueryClient();
  return useMutation<Me, Error, DisplayCurrency, { previous?: Me }>({
    mutationFn: async (currency) =>
      apiPatch<Me>("/api/v1/users/me", { display_currency: currency }),
    onMutate: async (currency) => {
      await qc.cancelQueries({ queryKey: ["me"] });
      const previous = qc.getQueryData<Me>(["me"]);
      if (previous) {
        qc.setQueryData<Me>(["me"], { ...previous, display_currency: currency });
      }
      return { previous };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) qc.setQueryData(["me"], ctx.previous);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["me"] });
      // Catalog responses bake the chosen currency into ``display_price`` —
      // they need a refetch on switch. Wallet shows a derived total too.
      void qc.invalidateQueries({ queryKey: ["brand"] });
      void qc.invalidateQueries({ queryKey: ["product"] });
      void qc.invalidateQueries({ queryKey: ["wallet"] });
    },
  });
}
