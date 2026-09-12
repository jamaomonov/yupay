"use client";

import { Eye, Heart, Share2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { useArticleEngagement } from "./ArticleEngagement";

interface Props {
  title: string;
}

export function LiveEngagementStats() {
  const t = useTranslations("web.blog");
  const { like_count: likes, view_count: views } = useArticleEngagement();
  return (
    <div className="text-tx-dim flex items-center gap-3 font-mono text-[11px]">
      <span
        className="inline-flex items-center gap-1"
        aria-label={t("viewsAria", { count: views })}
      >
        <Eye size={12} aria-hidden />
        {views}
      </span>
      <span
        className="inline-flex items-center gap-1"
        aria-label={t("likesAria", { count: likes })}
      >
        <Heart size={12} aria-hidden />
        {likes}
      </span>
    </div>
  );
}

export function ArticleActions({ title }: Props) {
  const t = useTranslations("web.blog");
  const { liked, like_count: likes, busy, toggleLike } = useArticleEngagement();
  const [copied, setCopied] = useState(false);

  async function share(): Promise<void> {
    const url = window.location.href;
    if (typeof navigator.share === "function") {
      try {
        await navigator.share({ title, url });
        return;
      } catch {
        /* dismissed — do not also copy */
        return;
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
    <div className="border-border mt-8 flex flex-wrap items-center gap-3 border-t pt-6">
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
        className="border-border text-tx-mute hover:border-primary/30 hover:text-foreground inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-medium transition"
      >
        <Share2 size={16} aria-hidden />
        {copied ? t("copied") : t("share")}
      </button>
    </div>
  );
}
