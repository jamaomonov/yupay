/**
 * Static catalog data. Hardcoded until the /catalog API is wired; the shape
 * mirrors the live `Brand`/`Product` contracts so swapping to the API is a
 * drop-in. Copy that must localise (name/eyebrow/tag/about) lives in
 * web.catalog.cards.* and web.store.brands.* — only structural data is here.
 *
 * Prices are display placeholders in whole som (UZS). They never touch the
 * money pipeline (which uses minor units); they exist to render plausible
 * offers + JSON-LD until real pricing arrives.
 */
export type BrandCategory = "games" | "wallets" | "subscriptions";

export interface Pack {
  id: string;
  /** ready label for currency packs, e.g. "60 UC", "$10" */
  label?: string;
  /** subscription duration in months (rendered with a localised unit) */
  months?: number;
  /** display price in whole som */
  priceUzs: number;
  /** optional bonus note, e.g. "+25 UC" */
  bonus?: string;
}

export interface Brand {
  /** also the i18n key under web.catalog.cards.* and web.store.brands.* */
  slug: string;
  /** clean proper name for <h1>, <title>, JSON-LD (not localised) */
  name: string;
  category: BrandCategory;
  /** background key-art in /public/brands */
  art: string;
  /** square brand mark (optional) */
  icon?: string;
  /** accent hue for tints/gradients */
  accent: string;
  /** lowest commission %, surfaced as "from N%" */
  commissionFrom: number;
  /** typical credit time, e.g. "1–2" (minutes) */
  etaMinutes: string;
  popular?: boolean;
  packs: Pack[];
}

export const BRANDS: Brand[] = [
  {
    slug: "steam",
    name: "Steam",
    category: "wallets",
    art: "/brands/steam-bg.jpg",
    accent: "#66c0f4",
    commissionFrom: 4,
    etaMinutes: "1–3",
    popular: true,
    packs: [
      { id: "steam-5", label: "$5", priceUzs: 72000 },
      { id: "steam-10", label: "$10", priceUzs: 143000 },
      { id: "steam-25", label: "$25", priceUzs: 356000 },
      { id: "steam-50", label: "$50", priceUzs: 710000 },
    ],
  },
  {
    slug: "pubg-mobile",
    name: "PUBG Mobile",
    category: "games",
    art: "/brands/pubg-bg.png",
    icon: "/brands/pubg-icon.svg",
    accent: "#f2a900",
    commissionFrom: 3,
    etaMinutes: "1–2",
    popular: true,
    packs: [
      { id: "uc-60", label: "60 UC", priceUzs: 11999 },
      { id: "uc-325", label: "300 UC", bonus: "+25 UC", priceUzs: 59990 },
      { id: "uc-660", label: "600 UC", bonus: "+60 UC", priceUzs: 119980 },
      { id: "uc-1800", label: "1500 UC", bonus: "+300 UC", priceUzs: 299950 },
    ],
  },
  {
    slug: "telegram-premium",
    name: "Telegram Premium",
    category: "subscriptions",
    art: "/brands/telegram-bg.jpg",
    icon: "/brands/telegram-icon.webp",
    accent: "#4fb4e0",
    commissionFrom: 3,
    etaMinutes: "1–2",
    popular: true,
    packs: [
      { id: "tg-1", months: 1, priceUzs: 49900 },
      { id: "tg-3", months: 3, priceUzs: 129900 },
      { id: "tg-6", months: 6, priceUzs: 229900 },
      { id: "tg-12", months: 12, priceUzs: 399900 },
    ],
  },
  {
    slug: "delta-force",
    name: "Delta Force",
    category: "games",
    art: "/brands/deltaforce.webp",
    accent: "#7bb43a",
    commissionFrom: 4,
    etaMinutes: "1–3",
    packs: [
      { id: "df-300", label: "300 Coins", priceUzs: 39990 },
      { id: "df-680", label: "680 Coins", priceUzs: 89990 },
      { id: "df-1480", label: "1480 Coins", priceUzs: 179990 },
      { id: "df-3280", label: "3280 Coins", priceUzs: 379990 },
    ],
  },
  {
    slug: "arena-breakout",
    name: "Arena Breakout",
    category: "games",
    art: "/brands/arenabreakout-bg.png",
    icon: "/brands/arenabreakout-icon.svg",
    accent: "#5ba8ff",
    commissionFrom: 4,
    etaMinutes: "1–3",
    packs: [
      { id: "ab-340", label: "340 Bonds", priceUzs: 44990 },
      { id: "ab-710", label: "710 Bonds", priceUzs: 89990 },
      { id: "ab-1840", label: "1840 Bonds", priceUzs: 219990 },
      { id: "ab-3880", label: "3880 Bonds", priceUzs: 449990 },
    ],
  },
];

export const CATEGORIES: BrandCategory[] = ["games", "wallets", "subscriptions"];

export function getBrand(slug: string): Brand | undefined {
  return BRANDS.find((b) => b.slug === slug);
}

export function brandSlugs(): string[] {
  return BRANDS.map((b) => b.slug);
}

export function brandsByCategory(cat?: string): Brand[] {
  if (!cat || cat === "all") return BRANDS;
  return BRANDS.filter((b) => b.category === cat);
}
