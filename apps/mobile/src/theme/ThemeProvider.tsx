import { createContext, use, useEffect, useState, type ReactNode } from "react";
import { useColorScheme } from "react-native";

import { readPref, writePref } from "@/lib/prefs";
import { palettes, type Palette, type Scheme } from "@/theme/tokens";

export type ThemePref = "system" | Scheme;

interface ThemeValue {
  scheme: Scheme;
  pref: ThemePref;
  setPref: (pref: ThemePref) => void;
  c: Palette;
}

const PREF_KEY = "theme";
const ThemeContext = createContext<ThemeValue | null>(null);

function isPref(value: string | null): value is ThemePref {
  return value === "system" || value === "light" || value === "dark";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const system = useColorScheme();
  const [pref, setPrefState] = useState<ThemePref>("system");

  useEffect(() => {
    void readPref(PREF_KEY).then((saved) => {
      if (isPref(saved)) setPrefState(saved);
    });
  }, []);

  const setPref = (next: ThemePref) => {
    setPrefState(next);
    void writePref(PREF_KEY, next);
  };

  const scheme: Scheme = pref === "system" ? (system === "light" ? "light" : "dark") : pref;
  return (
    <ThemeContext value={{ scheme, pref, setPref, c: palettes[scheme] }}>{children}</ThemeContext>
  );
}

export function useTheme(): ThemeValue {
  const value = use(ThemeContext);
  if (!value) throw new Error("useTheme outside ThemeProvider");
  return value;
}
