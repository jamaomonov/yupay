export interface ProviderDisplay {
  /** A proper brand name rendered as-is (Click, Payme, …) or an unknown slug. */
  name?: string;
  /** An i18n key under the `orders` namespace for a localized label (wallet). */
  nameKey?: string;
  /** Public path to a logo asset, when one exists. */
  logo?: string;
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
