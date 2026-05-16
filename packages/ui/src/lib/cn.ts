import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge Tailwind class names while resolving conflicts deterministically.
 * Prefer this over raw `clsx` so duplicate utilities collapse.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
