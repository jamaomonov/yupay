/**
 * Renders a lucide-react icon looked up by its kebab-case name (e.g.
 * ``"gamepad-2"`` → ``Gamepad2``) — the format operators type into free-text
 * icon fields (see `CategoryEditPage`). Falls back to the raw name (or a
 * custom fallback) when the string doesn't match a known icon, so a typo
 * never renders a blank cell.
 */

import * as LucideIcons from "lucide-react";

import type { LucideIcon as LucideIconType } from "lucide-react";
import type { ReactNode } from "react";

interface Props {
  name: string | null | undefined;
  className?: string;
  /** Shown when `name` is empty or doesn't match a known icon. Defaults to
   *  the raw name in a `<code>` tag (or `null` when `name` is empty). */
  fallback?: ReactNode;
}

function toPascalCase(name: string): string {
  return name
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => (part[0] ?? "").toUpperCase() + part.slice(1))
    .join("");
}

export function DynamicIcon({ name, className, fallback }: Props) {
  if (!name) return <>{fallback ?? null}</>;
  // lucide-react's barrel export has no index signature (each icon is a
  // named export), so a dynamic string lookup needs a narrowing cast — the
  // shape (a map of PascalCase name -> component) is documented by the
  // library itself.
  const icons = LucideIcons as unknown as Record<string, LucideIconType>;
  const Icon = icons[toPascalCase(name)];
  if (!Icon) {
    return <>{fallback ?? <code className="text-xs">{name}</code>}</>;
  }
  return <Icon className={className} aria-hidden />;
}
