"use client";

import { useState } from "react";

/**
 * The brand "Об услуге" copy. On phones the text is long enough to bury the
 * FAQ and reviews below a wall of scrolling, so it's clamped with a
 * "Читать далее" toggle there; on sm+ it always renders in full (the desktop
 * left column has the room, and the full text stays in the DOM for SEO
 * regardless — CSS clamps it, it isn't removed).
 */
export function AboutText({
  text,
  moreLabel,
  lessLabel,
}: {
  text: string;
  moreLabel: string;
  lessLabel: string;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div>
      <p
        className={`text-tx-mute mt-3 whitespace-pre-line text-[15px] leading-relaxed ${
          expanded ? "" : "line-clamp-6 sm:line-clamp-none"
        }`}
      >
        {text}
      </p>
      <button
        type="button"
        onClick={() => {
          setExpanded((v) => !v);
        }}
        aria-expanded={expanded}
        className="text-primary mt-2 min-h-[44px] text-[13px] font-semibold sm:hidden"
      >
        {expanded ? lessLabel : moreLabel}
      </button>
    </div>
  );
}
