/**
 * Region flags and the compact region switcher, shared by the storefront and
 * the Mini App.
 *
 * Flags are static SVGs (flag-icons, MIT) served from `/flags/region/<iso>.svg`
 * in both apps, not emoji: Windows renders a flag emoji as two letters, and a
 * good share of our desktop buyers are on Windows. Only the countries we sell
 * are shipped — {@link FLAG_CODES} is that list, and a test keeps it in step
 * with the files. A code that is not one country (global, cis, eu-wide bundles
 * like mena, latam) has no flag: the caller shows a globe instead.
 */

/** Every ISO code with a file under `/flags/region/`. */
export const FLAG_CODES: ReadonlySet<string> = new Set([
  "ad", "ae", "ar", "at", "au", "az", "bd", "be", "bg", "bh", "br", "by", "ca", "ch", "cl",
  "cn", "co", "cr", "cy", "cz", "de", "dk", "dz", "ee", "eg", "es", "eu", "fi", "fr", "gb",
  "gr", "hk", "hr", "hu", "id", "ie", "in", "iq", "it", "jo", "jp", "kh", "kr", "kw", "kz",
  "lb", "lu", "lv", "ma", "mo", "mv", "mx", "my", "ng", "nl", "no", "nz", "om", "pe", "ph",
  "pk", "pl", "pt", "qa", "ro", "ru", "sa", "se", "sg", "sk", "th", "tn", "tr", "tw", "ua",
  "us", "uy", "uz", "vn", "za",
]); // prettier-ignore

/** Our region codes that are not the country's ISO code, or name several. */
const ALIASES: Readonly<Record<string, string>> = {
  uk: "gb",
  mysg: "my",
  "my/sg": "my",
  "tw/hk/mo": "tw",
};

/** ISO code of the region's flag, or `null` when the region is not one country. */
export function regionFlagCode(region: string | null | undefined): string | null {
  if (!region) return null;
  const code = region.trim().toLowerCase();
  const iso = ALIASES[code] ?? code;
  return FLAG_CODES.has(iso) ? iso : null;
}

/** Public path of the region's flag, or `null` (show a globe). */
export function regionFlagSrc(region: string | null | undefined): string | null {
  const iso = regionFlagCode(region);
  return iso ? `/flags/region/${iso}.svg` : null;
}

/** The game's main region is labelled after Uzbekistan («Глобальный
 *  (Узбекистан)», «Узбекистан и СНГ»), so it carries our flag, not a globe. */
export function homeRegionFlagSrc(region: string, isHome: boolean): string | null {
  if (isHome && (region === "global" || region === "cis")) return regionFlagSrc("uz");
  return regionFlagSrc(region);
}

/** At this many regions the switcher folds the rest under «Все регионы». */
export const REGION_COMPACT_FROM = 11;
/** How many chips stay on screen once folded. */
export const REGION_TOP = 8;

/** The countries our buyers pick most, most first. The API's own order is
 *  built for MLBB's servers (Malaysia, Singapore…), which on a gift-card
 *  page like PlayStation put two rarely-bought countries second and third. */
export const POPULAR_REGIONS: readonly string[] = [
  "us", "tr", "uk", "de", "ae", "pl", "in", "kz", "ru", "eu", "sa", "br", "ca", "fr",
]; // prettier-ignore

export interface FoldedRegions {
  /** Codes shown as chips, in display order. */
  shown: string[];
  /** How many regions sit only in the full list. 0 means nothing is folded. */
  folded: number;
}

/**
 * Which regions stay on screen as chips.
 *
 * Under {@link REGION_COMPACT_FROM} nothing folds. Otherwise the game's main
 * region (the first one) leads, then the popular countries it sells, then the
 * API order, up to {@link REGION_TOP}. The picked region is always on screen:
 * picked from the full list, it takes the last chip rather than jumping the
 * row around.
 */
export function foldRegions(codes: readonly string[], current: string): FoldedRegions {
  if (codes.length < REGION_COMPACT_FROM) return { shown: [...codes], folded: 0 };
  const available = new Set(codes);
  const ordered = [
    ...codes.slice(0, 1),
    ...POPULAR_REGIONS.filter((c) => available.has(c)),
    ...codes,
  ];
  const shown = [...new Set(ordered)].slice(0, REGION_TOP);
  if (available.has(current) && !shown.includes(current)) shown[shown.length - 1] = current;
  return { shown, folded: codes.length - shown.length };
}

/** Case- and accent-insensitive match of a search query against a region. */
export function regionMatches(query: string, label: string, code: string): boolean {
  const q = normalise(query);
  if (!q) return true;
  return normalise(label).includes(q) || code.toLowerCase().startsWith(q);
}

function normalise(s: string): string {
  return s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().replace(/ё/g, "е").trim();
}
