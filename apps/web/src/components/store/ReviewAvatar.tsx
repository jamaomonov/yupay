"use client";

import { User } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export interface ReviewAvatarProps {
  /** The reviewer's public avatar, https only (the API drops anything else). */
  photoUrl: string | null | undefined;
  /** Display name — its first letter is the fallback. */
  name: string | null | undefined;
}

/**
 * The reviewer's picture beside their name, drawn like the mini app's header
 * avatar: a ring, the photo, and the initial when there is no photo.
 *
 * Client-side only for `onError`/`onLoad`. These URLs come from Telegram,
 * Google and Steam, which rotate them; a dead link must fall back to the
 * initial rather than leave a broken-image box on the brand page. Telegram
 * does not even fail a dead userpic: it answers 200 with an empty image,
 * which is why a 1-pixel "success" counts as a failure too.
 */
export function ReviewAvatar({ photoUrl, name }: ReviewAvatarProps) {
  const [failed, setFailed] = useState(false);
  const img = useRef<HTMLImageElement>(null);
  const initial = name?.trim()[0]?.toUpperCase();

  // The <img> is server-rendered, so it can finish — or fail — before React
  // attaches `onLoad`/`onError` and neither ever fires. Settle that case once
  // on mount; `complete` with a 0 width is an error, 1 is Telegram's blank.
  useEffect(() => {
    const el = img.current;
    if (el?.complete && el.naturalWidth < 2) setFailed(true);
  }, []);

  return (
    <span className="border-border bg-primary/20 text-primary flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full border text-xs font-bold">
      {photoUrl && !failed ? (
        // A plain <img>, not next/image: third-party hosts that change, one
        // 32px picture each, nothing for the optimizer to earn.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          ref={img}
          src={photoUrl}
          alt=""
          width={32}
          height={32}
          loading="lazy"
          referrerPolicy="no-referrer"
          className="h-full w-full object-cover"
          onError={() => {
            setFailed(true);
          }}
          onLoad={(ev) => {
            if (ev.currentTarget.naturalWidth < 2) setFailed(true);
          }}
        />
      ) : initial ? (
        <span aria-hidden="true">{initial}</span>
      ) : (
        <User size={14} aria-hidden="true" />
      )}
    </span>
  );
}
