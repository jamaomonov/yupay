export interface ProviderDisplay {
  /** A proper brand name rendered as-is (Click, Payme, …) or an unknown slug. */
  name?: string;
  /** An i18n key under the `orders` namespace for a localized label (wallet). */
  nameKey?: string;
  /** Public path to a logo asset, when one exists. */
  logo?: string;
}

/**
 * A payment provider's admin-controlled availability, mirroring the backend's
 * `ProviderStatusOut` (`apps/api/src/yupay/modules/payments/schemas.py`). Kept
 * as a local type rather than imported from `@yupay/api-client` because the
 * storefront hand-rolls this fetch instead of using the generated client —
 * see the `pay()` call in `PurchasePanel.tsx`.
 */
export type ProviderStatus = "active" | "maintenance";

export interface ProviderStatusEntry {
  slug: string;
  status: ProviderStatus;
}

/** Shape of `GET /api/v1/payments/providers`. */
export interface ProvidersOut {
  providers: ProviderStatusEntry[];
}

/**
 * Build a slug → status lookup from the providers response. A slug absent
 * from the map means the provider isn't offered at all (admin-disabled).
 */
export function providerStatusMap(payload: ProvidersOut): Map<string, ProviderStatus> {
  return new Map(payload.providers.map((p) => [p.slug, p.status]));
}

export type MethodVisibility = "active" | "maintenance" | "hidden";

/**
 * Resolve how a storefront payment method should render, given the live
 * provider-status map:
 * - `statusBySlug === null` means the fetch hasn't resolved yet (or failed) —
 *   this fails OPEN, rendering every method as `"active"`, so a slow network
 *   or a transient error never blanks out the checkout's payment methods.
 * - Once loaded, a slug absent from the map is `"hidden"` (not offered).
 * - `"maintenance"` renders the method but keeps it non-clickable;
 *   `"active"` is selectable exactly as before this admin control existed.
 */
export function methodVisibility(
  provider: string,
  statusBySlug: Map<string, ProviderStatus> | null,
): MethodVisibility {
  if (statusBySlug === null) return "active";
  return statusBySlug.get(provider) ?? "hidden";
}

interface MethodLike {
  id: string;
  provider: string;
}

/**
 * Once live provider status has loaded, decide which method id should be
 * selected: keep `currentId` when its provider is `"active"`; otherwise fall
 * back to the first method whose provider is `"active"`; if none are, return
 * `null` — nothing is selectable, and the caller must not let checkout
 * proceed. This exists so a hardcoded UI default (e.g. the first method in a
 * fixed list) can never stay silently selected once it's known to be under
 * maintenance or admin-disabled.
 */
export function selectActiveMethodId(
  methods: MethodLike[],
  currentId: string,
  statusBySlug: Map<string, ProviderStatus>,
): string | null {
  const current = methods.find((m) => m.id === currentId);
  if (current && statusBySlug.get(current.provider) === "active") {
    return currentId;
  }
  const firstActive = methods.find((m) => statusBySlug.get(m.provider) === "active");
  return firstActive?.id ?? null;
}

/**
 * Map a payment-provider slug to how the customer should see it on an order.
 * Backend already normalizes `click_miniapp` → `click`; we tolerate both.
 * Returns null when there is no provider yet (unpaid order).
 */
export function paymentProviderDisplay(provider: string | null): ProviderDisplay | null {
  switch (provider) {
    case "click":
    case "click_miniapp":
      return { name: "Click", logo: "/payment/click.svg" };
    case "payme":
      return { name: "Payme", logo: "/payment/payme.png" };
    case "uzum":
      return { name: "Uzum", logo: "/payment/uzum.png" };
    case "octo":
      return { name: "Octo" };
    case "wallet":
      return { nameKey: "paidWithWallet" };
    case null:
    case "":
      return null;
    default:
      return { name: provider };
  }
}
