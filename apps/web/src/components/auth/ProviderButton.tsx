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
      className={`relative flex h-[52px] items-center justify-center gap-2.5 rounded-[14px] px-4 text-[15px] font-semibold transition ${surface} ${
        soon ? "cursor-not-allowed opacity-55" : "hover:brightness-110"
      }`}
    >
      <span className="flex items-center">{icon}</span>
      <span>{label}</span>
      {soon && (
        <span className="bg-bg/70 text-tx-mute absolute right-2 top-1.5 rounded-full px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide">
          {t("soon")}
        </span>
      )}
    </button>
  );
}
