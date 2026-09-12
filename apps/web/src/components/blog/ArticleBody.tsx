"use client";

/**
 * Render sanitized article HTML. The API already ran the allowlist; this is
 * presentation only. Tiny (1×1) tracking-style images are hidden after load.
 */

import { useLayoutEffect, useRef } from "react";

export function ArticleBody({ html }: { html: string }) {
  const ref = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const root = ref.current;
    if (!root) return;
    const hideTiny = (img: HTMLImageElement) => {
      if (img.naturalWidth > 0 && img.naturalWidth <= 2 && img.naturalHeight <= 2) {
        img.hidden = true;
      }
    };
    const nodes = root.querySelectorAll("img");
    nodes.forEach((img) => {
      if (img.complete) hideTiny(img);
      else img.addEventListener("load", () => hideTiny(img), { once: true });
    });
  }, [html]);

  return (
    <div
      ref={ref}
      className="article-body text-tx-mute text-[16px] leading-relaxed"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
