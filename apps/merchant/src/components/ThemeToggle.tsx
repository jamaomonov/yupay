"use client";

import { Moon, Sun } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { applyTheme, storedTheme, type Theme } from "@/lib/theme";

export function ThemeToggle() {
  const t = useTranslations("merchant.cabinet");
  // Starts as null, not "dark": the real answer lives in localStorage, which
  // the server cannot read, and rendering an icon for a guess would flip it on
  // hydration.
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    setTheme(storedTheme() ?? "dark");
  }, []);

  if (theme === null) return <span className="h-9 w-9" aria-hidden="true" />;

  const next: Theme = theme === "dark" ? "light" : "dark";
  const Icon = theme === "dark" ? Sun : Moon;
  return (
    <button
      type="button"
      aria-label={t("themeToggle")}
      onClick={() => {
        applyTheme(next);
        setTheme(next);
      }}
      className="border-border text-tx-mute flex h-9 w-9 items-center justify-center rounded-full border"
    >
      <Icon size={16} />
    </button>
  );
}
