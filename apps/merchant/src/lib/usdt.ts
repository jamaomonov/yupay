import { type Phase } from "./p2p";

import type { UsdtDeposit, UsdtNetwork } from "./types";

interface UsdtNetworkSpec {
  /** The chain's own name — a proper noun, the same in every locale. */
  name: string;
  /** The token standard wallets and exchanges list it under. */
  standard: string;
  /** The official USDT contract on this chain, as Trust Wallet names the asset. */
  trustAsset: string;
  /** The explorer's transaction page, without the hash. */
  txUrl: string;
  /** Gas is dear here: the picker says so. */
  costly: boolean;
  /** The chain's round logo, 128×128 on transparent, under `public/`. */
  logo: string;
}

/** Everything that differs between the chains a USDT top-up can use. */
export const USDT_NETWORKS: Readonly<Record<UsdtNetwork, UsdtNetworkSpec>> = {
  trc20: {
    name: "TRON",
    standard: "TRC20",
    trustAsset: "c195_tTR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
    txUrl: "https://tronscan.org/#/transaction/",
    logo: "/crypto/tron.png",
    costly: false,
  },
  bep20: {
    name: "BNB Chain",
    standard: "BEP20",
    trustAsset: "c20000714_t0x55d398326f99059fF775485246999027B3197955",
    txUrl: "https://bscscan.com/tx/",
    logo: "/crypto/bnb.png",
    costly: false,
  },
  erc20: {
    name: "Ethereum",
    standard: "ERC20",
    trustAsset: "c60_t0xdAC17F958D2ee523a2206206994597C13D831ec7",
    txUrl: "https://etherscan.io/tx/",
    logo: "/crypto/eth.png",
    costly: true,
  },
};

/** Whether a code from the API is a chain this build knows. */
export function isUsdtNetwork(value: string): value is UsdtNetwork {
  return Object.hasOwn(USDT_NETWORKS, value);
}

/** "TRON (TRC20)" — how the details and the paid screen name a chain. */
export function networkLabel(network: UsdtNetwork): string {
  const spec = USDT_NETWORKS[network];
  return `${spec.name} (${spec.standard})`;
}

/** Tether's round logo, the same size and shape as the chains'. */
export const USDT_LOGO = "/crypto/usdt.png";

/** Quick picks on the amount step, in whole USDT. */
export const USDT_PRESETS = [100, 500, 1000, 3000] as const;

/** Which screen a USDT top-up belongs on — the same screens as a card top-up. */
export function usdtPhase(d: UsdtDeposit | null): Phase {
  if (d === null) return "amount";
  switch (d.status) {
    case "pending":
      return "details";
    case "paid":
      return "paid";
    case "expired":
      return "expired";
    case "cancelled":
      return "cancelled";
  }
}

/**
 * How long to keep asking after expiry. The chain's block time decides a match,
 * so a transfer made in time but read late still pays the reservation.
 */
export const USDT_LATE_MS = 10 * 60 * 1000;

/** Until when to poll a USDT top-up, in epoch ms, or `null` to stop. */
export function usdtPollDeadline(d: UsdtDeposit | null): number | null {
  if (d === null || (d.status !== "pending" && d.status !== "expired")) return null;
  return Date.parse(d.expires_at) + USDT_LATE_MS;
}

/**
 * What the amount box keeps from a keystroke: digits and one decimal point
 * (a comma counts as one), at most two decimals and seven whole digits.
 */
export function sanitizeAmount(raw: string): string {
  const clean = raw.replace(/,/g, ".").replace(/[^\d.]/g, "");
  const dot = clean.indexOf(".");
  if (dot === -1) return clean.slice(0, 7);
  const whole = clean.slice(0, dot).slice(0, 7);
  const fraction = clean
    .slice(dot + 1)
    .replace(/\./g, "")
    .slice(0, 2);
  return `${whole === "" ? "0" : whole}.${fraction}`;
}

/** A decimal string as integer cents, or `null` when it is not one with ≤ 2 decimals. */
export function toCents(value: string): bigint | null {
  const match = /^(\d+)(?:\.(\d{0,2}))?$/.exec(value);
  if (match === null) return null;
  return BigInt(match[1] ?? "0") * 100n + BigInt((match[2] ?? "").padEnd(2, "0"));
}

export type AmountCheck = "empty" | "low" | "high" | "ok";

/** Whether an amount may be sent, against the bounds the status gave (either may be missing). */
export function checkAmount(value: string, min: string | null, max: string | null): AmountCheck {
  const cents = toCents(value);
  if (cents === null || cents === 0n) return "empty";
  const lo = min === null ? null : toCents(min);
  const hi = max === null ? null : toCents(max);
  if (lo !== null && cents < lo) return "low";
  if (hi !== null && cents > hi) return "high";
  return "ok";
}

/**
 * "1 234.50" in the cabinet's locale, from the server's decimal string — no
 * float touches it. Anything that is not a plain decimal is shown as sent.
 */
export function formatUsdt(amount: string, locale: string): string {
  const match = /^(\d+)(?:\.(\d+))?$/.exec(amount);
  if (match === null) return amount;
  const whole = new Intl.NumberFormat(locale).format(BigInt(match[1] ?? "0"));
  const decimal =
    new Intl.NumberFormat(locale).formatToParts(1.5).find((part) => part.type === "decimal")
      ?.value ?? ".";
  const cents = (match[2] ?? "").padEnd(2, "0");
  return cents === "00" ? whole : `${whole}${decimal}${cents}`;
}

/**
 * "1 000.00" — the amount to send, grouped by thousands with a narrow
 * no-break space but keeping the point: a wallet's send form takes a point,
 * and a locale comma read by eye is the wrong number. Display only — the copy
 * button still hands over the raw string. Anything else is shown as sent.
 */
export function groupUsdt(amount: string): string {
  const match = /^(\d+)(\.\d+)?$/.exec(amount);
  if (match === null) return amount;
  const whole = (match[1] ?? "").replace(/\B(?=(\d{3})+(?!\d))/g, "\u202F");
  return `${whole}${match[2] ?? ""}`;
}

/** Whether the amount box holds exactly this whole preset. */
export function isPreset(amount: string, preset: number): boolean {
  return toCents(amount) === BigInt(preset) * 100n;
}

/** Trust Wallet's send screen with the address and amount filled in. */
export function trustWalletLink(network: UsdtNetwork, address: string, amount: string): string {
  const asset = USDT_NETWORKS[network].trustAsset;
  const query = new URLSearchParams({ asset, address, amount });
  return `https://link.trustwallet.com/send?${query.toString()}`;
}

/** The transaction on the chain's explorer. */
export function explorerTxLink(network: UsdtNetwork, txId: string): string {
  return `${USDT_NETWORKS[network].txUrl}${encodeURIComponent(txId)}`;
}

/** "a1b2c3…d4e5f6" — enough of a hash to recognise it. */
export function shortHash(hash: string): string {
  return hash.length <= 14 ? hash : `${hash.slice(0, 6)}…${hash.slice(-6)}`;
}

/** The `topUpUsdt.*` message key for an API error code, or `null` for "something else". */
export function usdtErrorKey(
  code: string | null,
): "errPrecision" | "errAmountBusy" | "errRetry" | "errTooMany" | "errNetworkOff" | null {
  if (code === "usdt_amount_precision") return "errPrecision";
  if (code === "usdt_amount_busy") return "errAmountBusy";
  if (code === "usdt_idempotency_mismatch") return "errRetry";
  if (code === "usdt_too_many") return "errTooMany";
  if (code === "usdt_network_disabled") return "errNetworkOff";
  return null;
}
