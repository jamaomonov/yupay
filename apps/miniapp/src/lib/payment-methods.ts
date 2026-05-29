/**
 * Canonical list of external payment acquirers — the single source of truth
 * shared by the order checkout (``TopUp``) and the wallet top-up
 * (``WalletTopUp``) pages so the two never drift apart again.
 *
 * Each entry maps a UI method id to a backend ``payments.gateways`` provider
 * slug. Whether a method is actually usable right now is decided at render time
 * from ``GET /payments/providers`` (``useAvailableProviders``) — not here.
 *
 * The wallet ("pay from balance") option is intentionally NOT in this list: it
 * only applies to order checkout and is rendered as its own card in ``TopUp``.
 */

import clickIcon from "@/assets/payments/click.png";
import inpayIcon from "@/assets/payments/inpay.png";
import paymeIcon from "@/assets/payments/payme.png";
import usdtIcon from "@/assets/payments/usdt.png";
import uzumIcon from "@/assets/payments/uzum.png";

export interface PaymentMethod {
  /** UI id (also the selected-method key on both pages). */
  id: string;
  /** Brand display name. */
  name: string;
  /** Short subtitle / hint. */
  sub: string;
  /** Backend provider slug in ``payments.gateways`` REGISTRY. */
  provider: string;
  /** Currency the acquirer charges in. */
  currency: string;
  /** Brand logo, imported as a URL by Vite. */
  icon: string;
}

export const PAYMENT_METHODS: PaymentMethod[] = [
  {
    id: "inpay",
    name: "InPay",
    sub: "Click · Payme · карты",
    provider: "inpay",
    currency: "UZS",
    icon: inpayIcon,
  },
  {
    id: "click",
    name: "Click",
    sub: "Карта · Humo · Uzcard",
    provider: "click",
    currency: "UZS",
    icon: clickIcon,
  },
  {
    id: "payme",
    name: "Payme",
    sub: "Карта · Humo · Uzcard",
    provider: "payme",
    currency: "UZS",
    icon: paymeIcon,
  },
  {
    id: "uzum",
    name: "Uzum",
    sub: "Humo · Uzcard",
    provider: "uzum",
    currency: "UZS",
    icon: uzumIcon,
  },
  {
    id: "usdt",
    name: "USDT",
    sub: "TRC-20 / ERC-20",
    provider: "crypto",
    currency: "USDT",
    icon: usdtIcon,
  },
];

/** method id → backend provider slug. */
export const PROVIDER_BY_METHOD: Record<string, string> = Object.fromEntries(
  PAYMENT_METHODS.map((m) => [m.id, m.provider]),
);

export interface AcquirerInfo {
  label: string;
  currency: string;
}

/** method id → what the customer sees on their statement (label + currency). */
export const ACQUIRER_BY_METHOD: Record<string, AcquirerInfo> = Object.fromEntries(
  PAYMENT_METHODS.map((m) => [m.id, { label: m.name, currency: m.currency }]),
);
