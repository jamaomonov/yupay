import { useEffect, useState } from "react";

/**
 * A catalogue row's picture, at list size.
 *
 * The lists identified brands, products and SKUs by name alone, so finding one
 * meant reading every row — and an operator who works in this catalogue daily
 * recognises the artwork long before the text. It is a second, faster handle on
 * the same row, never the only one: the name stays beside it.
 *
 * Falls back to the first letter rather than a blank square, because a missing
 * image and a broken URL look identical to a hole in the layout and neither is
 * worth a support question. `onError` covers the URL that 404s — a `src` that
 * merely exists is not a picture that loads, and the CDN has been pruned before.
 */
export function Thumb({
  src,
  name,
  size = 24,
}: {
  src: string | null | undefined;
  name: string;
  /** Square edge in px. 24 in dense tables, 32 where the row is roomier. */
  size?: number;
}) {
  const [failed, setFailed] = useState(false);
  // A row can be re-rendered with a different image (search filters the list in
  // place); without this the previous failure would suppress the new picture.
  useEffect(() => {
    setFailed(false);
  }, [src]);

  const box = { width: size, height: size } as const;
  if (!src || failed) {
    return (
      <span
        aria-hidden="true"
        style={box}
        className="inline-flex flex-shrink-0 items-center justify-center rounded-md bg-[var(--bg-muted)] text-[10px] font-bold uppercase text-[var(--text-secondary)]"
      >
        {name.trim().charAt(0) || "—"}
      </span>
    );
  }
  return (
    <img
      src={src}
      alt=""
      aria-hidden="true"
      loading="lazy"
      style={box}
      onError={() => {
        setFailed(true);
      }}
      className="inline-block flex-shrink-0 rounded-md object-cover"
    />
  );
}
