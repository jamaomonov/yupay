import Image from "next/image";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { eventChip, type BlogListItem, type PostKind } from "@/lib/blog";
import { isOptimizable } from "@/lib/image";
import { pathFor } from "@/lib/seo";

const KIND_KEY: Record<PostKind, "kind.guide" | "kind.news" | "kind.update" | "kind.event"> = {
  guide: "kind.guide",
  news: "kind.news",
  update: "kind.update",
  event: "kind.event",
};

function formatDay(locale: string, iso: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(new Date(iso));
}

export async function BlogPostCard({
  post,
  locale,
}: {
  post: BlogListItem;
  locale: string;
}) {
  const t = await getTranslations("web.blog");
  const chip = eventChip(post);
  const kindLabel = t(KIND_KEY[post.kind]);

  return (
    <Link
      href={pathFor(locale, `/blog/${post.slug}`)}
      className="border-border hover:border-primary/30 bg-card group flex flex-col overflow-hidden rounded-2xl border transition hover:-translate-y-0.5"
    >
      <div className="bg-card-2 relative aspect-video">
        {post.cover_image_url ? (
          <Image
            src={post.cover_image_url}
            alt=""
            fill
            unoptimized={!isOptimizable(post.cover_image_url)}
            sizes="(max-width: 768px) 100vw, 360px"
            className="object-cover"
          />
        ) : null}
      </div>
      <div className="flex flex-1 flex-col gap-2 p-4">
        <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] uppercase tracking-[0.06em]">
          <span className="text-primary">{kindLabel}</span>
          {chip === "live" ? <span className="text-primary">{t("live")}</span> : null}
          {chip === "ended" ? <span className="text-tx-dim">{t("ended")}</span> : null}
          {post.pin_on_brand ? <span className="text-tx-mute">{t("pinned")}</span> : null}
        </div>
        <h2 className="font-display text-lg font-semibold tracking-[-0.02em] group-hover:text-primary">
          {post.title}
        </h2>
        {post.excerpt ? <p className="text-tx-mute line-clamp-3 text-sm leading-relaxed">{post.excerpt}</p> : null}
        <time className="text-tx-dim mt-auto font-mono text-[11px]" dateTime={post.updated_at}>
          {formatDay(locale, post.updated_at)}
        </time>
      </div>
    </Link>
  );
}
