/**
 * Shared shape types for the miniapp UI — extracted so both the mock data in
 * ``constants.ts`` and the API adapters in ``catalog.ts`` produce the same
 * thing.
 */

import type { ComponentType, CSSProperties } from "react";

export type GameIconComponent = ComponentType<{ style?: CSSProperties }>;

export type Category = "games" | "services" | "cards";

export type Game = {
  id: string;
  name: string;
  publisher: string;
  category: Category;
  /** Real category slug from the API (e.g. "games", "subscriptions"). Optional
   *  for backwards-compat with the mock data in ``constants.ts``. */
  category_slug?: string;
  appIcon?: string;
  logoUrl?: string;
  bgUrl?: string;
  icon?: GameIconComponent;
  iconColor?: string;
  color: string;
  gradient?: string;
  inputType: string;
  inputPlaceholder: string;
  featured?: boolean;
  featuredDesc?: string;
};
