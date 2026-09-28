"use client";

import { useEffect, useRef } from "react";

import type { ReactNode } from "react";

/**
 * A horizontal chip row that scrolls its `aria-current` child into view on
 * mount — on a phone the chosen category («Ножи») otherwise sits off-screen.
 */
export function ScrollActiveIntoView({
  className,
  activeKey,
  children,
}: {
  className: string;
  /** Re-centre only when the chosen item changes, not on every render. */
  activeKey: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const row = ref.current;
    const active = row?.querySelector<HTMLElement>('[aria-current="page"]');
    if (!row || !active || row.scrollWidth <= row.clientWidth) return;
    row.scrollLeft = active.offsetLeft - (row.clientWidth - active.offsetWidth) / 2;
  }, [activeKey]);
  return (
    // `relative`: offsetLeft is measured from the nearest positioned ancestor.
    <div ref={ref} className={`relative ${className}`}>
      {children}
    </div>
  );
}
