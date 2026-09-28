/** Steam's wear bands by float value — the thresholds CS2 itself uses. */
export type WearBand = "FN" | "MW" | "FT" | "WW" | "BS";

const BANDS: readonly (readonly [number, WearBand])[] = [
  [0.07, "FN"],
  [0.15, "MW"],
  [0.38, "FT"],
  [0.45, "WW"],
];

export function wearBand(value: number): WearBand {
  for (const [upper, band] of BANDS) if (value < upper) return band;
  return "BS";
}

/** Marker position on a 0..1 float bar, as a percent. */
export function floatPosition(value: number): number {
  return Math.min(100, Math.max(0, value * 100));
}

const ECONOMY = /^(https:\/\/[^/]+\/economy\/image\/[^/?#]+)(\/\d+fx\d+f)?$/;

/**
 * A Steam economy image at a given size (`256fx256f`): the full PNG is ~100 KB,
 * the 256 px one ~35 KB, and a grid of 48 cards pays that difference 48 times.
 */
export function steamImageSize(url: string, size: `${number}fx${number}f`): string {
  const match = ECONOMY.exec(url);
  return match?.[1] ? `${match[1]}/${size}` : url;
}
