"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { apiFetch } from "@/lib/client";

interface Engagement {
  liked: boolean;
  like_count: number;
  view_count: number;
}

interface Value extends Engagement {
  busy: boolean;
  toggleLike: () => Promise<void>;
}

const Ctx = createContext<Value | null>(null);

function idemHeaders(): Record<string, string> {
  return { "Idempotency-Key": crypto.randomUUID() };
}

export function ArticleEngagementProvider({
  slug,
  locale,
  initialLikes,
  initialViews,
  children,
}: {
  slug: string;
  locale: string;
  initialLikes: number;
  initialViews: number;
  children: ReactNode;
}) {
  const [liked, setLiked] = useState(false);
  const [likes, setLikes] = useState(initialLikes);
  const [views, setViews] = useState(initialViews);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void apiFetch<Engagement>(`/blog/${encodeURIComponent(slug)}/view?locale=${locale}`, {
      method: "POST",
      anonymous: true,
      headers: idemHeaders(),
    })
      .then((out) => {
        if (cancelled) return;
        setLiked(out.liked);
        setLikes(out.like_count);
        setViews(out.view_count);
      })
      .catch(() => {
        /* keep the SSR counts */
      });
    return () => {
      cancelled = true;
    };
  }, [locale, slug]);

  const value = useMemo<Value>(
    () => ({
      liked,
      like_count: likes,
      view_count: views,
      busy,
      toggleLike: async () => {
        if (busy) return;
        setBusy(true);
        const path = `/blog/${encodeURIComponent(slug)}/like?locale=${locale}`;
        try {
          const out = await apiFetch<Engagement>(path, {
            method: liked ? "DELETE" : "POST",
            anonymous: true,
            headers: idemHeaders(),
          });
          setLiked(out.liked);
          setLikes(out.like_count);
          setViews(out.view_count);
        } catch {
          /* keep the last good state */
        } finally {
          setBusy(false);
        }
      },
    }),
    [busy, liked, likes, locale, slug, views],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useArticleEngagement(): Value {
  const ctx = useContext(Ctx);
  if (!ctx) {
    throw new Error("useArticleEngagement needs ArticleEngagementProvider");
  }
  return ctx;
}
