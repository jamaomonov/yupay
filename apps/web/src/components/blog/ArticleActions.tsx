"use client";

import { Heart, Share2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/client";

interface Engagement {
  liked: boolean;
  like_count: number;
  view_count: number;
}

interface Props {
  slug: string;
  locale: string;
  title: string;
  initialLikes: number;
}

function idemHeaders(): Record<string, string> {
  return { "Idempotency-Key": crypto.randomUUID() };
}

/** One view POST per slug per tab. Dev Strict Mode remounts the effect. */
const viewStarted = new Set<string>();

export function ArticleActions({ slug, locale, title, initialLikes }: Props) {
  const t = useTranslations("web.blog");
  const [liked, setLiked] = useState(false);
  const [likes, setLikes] = useState(initialLikes);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (viewStarted.has(slug)) return;
    viewStarted.add(slug);
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
      })
      .catch(() => {
        viewStarted.delete(slug);
      });
    return () => {
      cancelled = true;
    };
  }, [locale, slug]);

  async function toggleLike(): Promise<void> {
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
    } catch {
      /* keep the last good state */
    } finally {
      setBusy(false);
    }
  }

  async function share(): Promise<void> {
    const url = window.location.href;
    if (typeof navigator.share === "function") {
      try {
        await navigator.share({ title, url });
        return;
      } catch {
        /* fall through to clipboard when the sheet is dismissed */
      }
    }
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => {
        setCopied(false);
      }, 2000);
    } catch {
      /* no clipboard permission */
    }
  }

  return (
    <div className="border-border mt-10 flex flex-wrap items-center gap-3 border-t pt-6">
      <button
        type="button"
        onClick={() => {
          void toggleLike();
        }}
        disabled={busy}
        aria-pressed={liked}
        className={`inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-medium transition ${
          liked
            ? "border-primary/40 bg-primary/10 text-primary"
            : "border-border text-tx-mute hover:border-primary/30 hover:text-foreground"
        }`}
      >
        <Heart size={16} fill={liked ? "currentColor" : "none"} aria-hidden />
        {t("like")}
        <span className="font-mono text-[12px]">{likes}</span>
      </button>
      <button
        type="button"
        onClick={() => {
          void share();
        }}
        className="bg-primary text-primary-foreground hover:brightness-110 inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold shadow-[0_10px_24px_-12px_hsl(var(--primary)/0.7)] transition"
      >
        <Share2 size={16} aria-hidden />
        {copied ? t("copied") : t("share")}
      </button>
    </div>
  );
}
