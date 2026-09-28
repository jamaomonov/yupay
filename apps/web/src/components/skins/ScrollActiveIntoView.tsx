"use client";

import { useEffect, useRef } from "react";

import type { ReactNode } from "react";

/**
 * A horizontal chip row that scrolls its `aria-current` child into view on
 * mount — on a phone the chosen category («Ножи») otherwise sits off-screen.
 */
export function ScrollActiveIntoView({
  className,
  children,
}: {
  className: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const row = ref.current;
    const active = row?.querySelector<HTMLElement>('[aria-current="page"]');
    if (!row || !active || row.scrollWidth <= row.clientWidth) return;
    row.scrollLeft = active.offsetLeft - (row.clientWidth - active.offsetWidth) / 2;
  });
  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}
