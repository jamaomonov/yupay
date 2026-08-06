"use client";

import { useTranslations } from "next-intl";

import type { ReactNode } from "react";

export interface ProviderButtonProps {
  label: string;
  icon: ReactNode;
  /** Tailwind classes for the button surface (background/text/border). */
  surface: string;
  onClick?: () => void;
  soon?: boolean;
}

/** A single provider tile in the login modal grid. `soon` => inert + "скоро" badge. */
export function ProviderButton({ label, icon, surface, onClick, soon }: ProviderButtonProps) {
  const t = useTranslations("web.auth");
  return (
    <button
      type="button"
      disabled={soon}
      aria-disabled={soon}
      onClick={soon ? undefined : onClick}
      className={`relative flex h-[52px] items-center justify-center gap-2.5 rounded-lg px-4 text-[15px] font-semibold transition ${surface} ${
        soon ? "cursor-not-allowed opacity-55" : "hover:brightness-110"
      }`}
    >
      <span className="flex items-center">{icon}</span>
      <span>{label}</span>
      {soon && (
        <span className="bg-bg text-tx-mute absolute right-1 top-1 z-10 rounded-full px-1 py-[3px] text-[9px] font-bold uppercase leading-none tracking-wide">
          {t("soon")}
        </span>
      )}
    </button>
  );
}
