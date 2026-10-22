/**
 * Design tokens for the app (ADR-0100).
 *
 * The dark palette started as the web storefront's (`apps/web/src/app/globals.css`) and was
 * lifted to graphite-navy on 2026-10-22; the light one is the app's own. Lime is a fill, never text on white — `accent` is the readable green for links and
 * small highlights in the light theme.
 */

export interface Palette {
  bg: string;
  card: string;
  muted: string;
  border: string;
  fg: string;
  mute: string;
  dim: string;
  primary: string;
  primaryFg: string;
  accent: string;
  selBg: string;
  selBorder: string;
  ok: string;
  okBg: string;
  warn: string;
  warnBg: string;
  danger: string;
  dangerBg: string;
}

export type Scheme = "light" | "dark";

export const palettes: Record<Scheme, Palette> = {
  light: {
    bg: "#EEF0F4",
    card: "#FFFFFF",
    muted: "#E4E7ED",
    border: "#DDE1E8",
    fg: "#0B0D17",
    mute: "#5B6275",
    dim: "#8D93A5",
    primary: "#AAFF33",
    primaryFg: "#000000",
    accent: "#3D7A00",
    selBg: "#F3FFE3",
    selBorder: "#8BD420",
    ok: "#16794A",
    okBg: "#E3F4EA",
    warn: "#965A00",
    warnBg: "#FFF4E0",
    danger: "#D92D20",
    dangerBg: "#FEECEB",
  },
  dark: {
    // Graphite-navy, not near-black: on #060712 the cards vanished and the screen read as a
    // hole (owner, 2026-10-22).
    bg: "#11141F",
    card: "#1A1E2D",
    muted: "#242939",
    border: "#2E3447",
    fg: "#FFFFFF",
    mute: "#A8B0C8",
    dim: "#7E87A3",
    primary: "#AAFF33",
    primaryFg: "#000000",
    accent: "#AAFF33",
    selBg: "rgba(170,255,51,0.08)",
    selBorder: "#AAFF33",
    ok: "#4ADE80",
    okBg: "rgba(74,222,128,0.10)",
    warn: "#FFC24D",
    warnBg: "rgba(255,194,77,0.10)",
    danger: "#F97066",
    dangerBg: "rgba(240,68,56,0.12)",
  },
};

export const radius = { control: 14, card: 20, tile: 16, small: 10 } as const;

/**
 * A soft drop shadow tinted with the light theme's ink; the dark theme separates layers by
 * colour instead, so it gets none.
 */
export function cardShadow(scheme: Scheme) {
  if (scheme === "dark") return {};
  return {
    shadowColor: "#0B0D17",
    shadowOpacity: 0.06,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  } as const;
}

/**
 * Font family names as registered by `useFonts` in the root layout. Two Inter weights carry
 * the hierarchy; Unbounded is for the large tab headings only.
 */
export const fonts = {
  medium: "Inter_500Medium",
  semibold: "Inter_600SemiBold",
  display: "Unbounded_600SemiBold",
} as const;

/** Spacing on the 4-pt grid; `gutter` is the screen's side margin. */
export const space = { gutter: 16, xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;

/** Every tappable thing is at least this tall and wide (Apple HIG, Material: 44–48). */
export const TOUCH = 44;
