/**
 * Theme state — three-way pick (light / dark / system) persisted in
 * localStorage. The anti-FOUC bootstrap in index.html runs before React
 * mounts and already sets `data-theme` on <html>; this store takes over after
 * mount, keeps the attribute in sync with user choices, and listens to the
 * OS preference change while the user is on `system` mode.
 */

import { useEffect } from "react";
import { create } from "zustand";

export type ThemeMode = "light" | "dark" | "system";
export type EffectiveTheme = "light" | "dark";

const STORAGE_KEY = "yupay.admin.theme";

function readStored(): ThemeMode {
  if (typeof window === "undefined") return "system";
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (raw === "light" || raw === "dark" || raw === "system") return raw;
  return "system";
}

function systemPrefersDark(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function resolveEffective(mode: ThemeMode): EffectiveTheme {
  if (mode === "system") return systemPrefersDark() ? "dark" : "light";
  return mode;
}

function applyToDocument(effective: EffectiveTheme): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", effective);
}

interface ThemeState {
  mode: ThemeMode;
  effective: EffectiveTheme;
  setMode: (next: ThemeMode) => void;
  /** Internal — re-evaluate `effective` (used by the system-pref listener). */
  refresh: () => void;
}

const initialMode = readStored();
applyToDocument(resolveEffective(initialMode));

export const useThemeStore = create<ThemeState>((set, get) => ({
  mode: initialMode,
  effective: resolveEffective(initialMode),
  setMode: (next) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // ignore — quota or private-mode failure; the in-memory state still wins.
    }
    const effective = resolveEffective(next);
    applyToDocument(effective);
    set({ mode: next, effective });
  },
  refresh: () => {
    const effective = resolveEffective(get().mode);
    applyToDocument(effective);
    set({ effective });
  },
}));

/**
 * Mount once at the root: subscribes to `matchMedia` so that — when the user
 * is on `system` mode — flipping the OS theme updates the SPA in real time.
 */
export function useSystemThemeSubscription(): void {
  const refresh = useThemeStore((s) => s.refresh);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (useThemeStore.getState().mode === "system") refresh();
    };
    mql.addEventListener("change", onChange);
    return () => {
      mql.removeEventListener("change", onChange);
    };
  }, [refresh]);
}
