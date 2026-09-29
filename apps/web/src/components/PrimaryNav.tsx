"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import type { NavLink } from "@/lib/primary-nav";

import { activeNavHref, primaryNavLinks } from "@/lib/primary-nav";

interface Props {
  locale: string;
  label: string;
  /** Each section's label, keyed as in `primaryNavLinks`. */
  labels: Record<NavLink["key"], string>;
  /** Whether the CS2 skins section is on. */
  skins: boolean;
}

export function PrimaryNav({ locale, label, labels, skins }: Props) {
  const pathname = usePathname();
  const links = primaryNavLinks(locale, skins);
  const active = activeNavHref(pathname, links);

  return (
    <nav aria-label={label} className="hidden items-center gap-8 lg:flex">
      {links.map((l) => (
        <Link
          key={l.key}
          href={l.href}
          aria-current={l.href === active ? "page" : undefined}
          className={`whitespace-nowrap text-sm font-medium transition ${
            l.href === active ? "text-foreground" : "text-tx-mute hover:text-foreground"
          }`}
        >
          {labels[l.key]}
        </Link>
      ))}
    </nav>
  );
}
