import { Headphones, ShieldCheck, Star } from "lucide-react";
import Image from "next/image";
import { getTranslations } from "next-intl/server";

import type { FeaturedReview } from "@/lib/reviews";

import { isOptimizable } from "@/lib/image";
import { getFeaturedReviews } from "@/lib/reviews";

/** Below this many there is nothing to scroll: the cards sit in a plain row. */
const MARQUEE_MIN = 6;

/** Avatar backgrounds for reviewers without a photo, picked by name so each stays put. */
const AVATAR_TINTS = [
  "from-[#7c3aed] to-[#db2777]",
  "from-[#0ea5e9] to-[#6366f1]",
  "from-[#f59e0b] to-[#ef4444]",
  "from-[#10b981] to-[#0ea5e9]",
  "from-[#a3e635] to-[#16a34a]",
  "from-[#f472b6] to-[#a855f7]",
] as const;

export function avatarTint(name: string): string {
  let h = 0;
  for (const ch of name) h = (h * 31 + (ch.codePointAt(0) ?? 0)) >>> 0;
  return AVATAR_TINTS[h % AVATAR_TINTS.length] ?? AVATAR_TINTS[0];
}

function Stars({ rating, label }: { rating: number; label: string }) {
  return (
    <span role="img" aria-label={label} className="flex gap-0.5">
      {[1, 2, 3, 4, 5].map((i) => (
        <Star
          key={i}
          size={13}
          aria-hidden
          className={i <= rating ? "fill-[#fbbf24] text-[#fbbf24]" : "text-white/15"}
        />
      ))}
    </span>
  );
}

export function ReviewCard({
  review,
  anonymous,
  starsLabel,
}: {
  review: FeaturedReview;
  anonymous: string;
  starsLabel: string;
}) {
  const name = review.author_name ?? anonymous;
  const photo = review.author_photo_url ?? null;
  const logo = review.brand_logo_url ?? null;
  return (
    <figure className="border-border bg-card/80 hover:border-border-2 flex h-full w-[300px] shrink-0 flex-col rounded-2xl border p-5 backdrop-blur transition sm:w-[340px]">
      <figcaption className="flex items-center gap-3">
        {photo ? (
          <Image
            src={photo}
            alt=""
            width={40}
            height={40}
            unoptimized={!isOptimizable(photo)}
            className="size-10 shrink-0 rounded-full object-cover ring-2 ring-white/10"
          />
        ) : (
          <span
            aria-hidden
            className={`flex size-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br text-[15px] font-bold text-white ring-2 ring-white/10 ${avatarTint(name)}`}
          >
            {name.trim().charAt(0).toUpperCase()}
          </span>
        )}
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[14px] font-semibold">{name}</span>
          <Stars rating={review.rating} label={starsLabel} />
        </span>
      </figcaption>
      {/* Always three lines tall — a short review keeps the space, a long one is cut —
          so every card in a row is the same height and the brand rows line up. */}
      <blockquote
        title={review.body ?? undefined}
        className="text-foreground/90 mt-4 line-clamp-3 min-h-[4.875em] text-[14px] leading-[1.625]"
      >
        «{review.body}»
      </blockquote>
      <span className="border-border mt-auto flex items-center gap-2 border-t pt-3.5">
        {logo ? (
          <Image
            src={logo}
            alt=""
            width={22}
            height={22}
            unoptimized={!isOptimizable(logo)}
            className="size-[22px] rounded-md object-cover"
          />
        ) : (
          <span
            aria-hidden
            className="bg-muted text-tx-mute flex size-[22px] shrink-0 items-center justify-center rounded-md text-[11px] font-bold"
          >
            {review.brand_name.charAt(0)}
          </span>
        )}
        <span className="text-tx-mute truncate text-[12px] font-medium">{review.brand_name}</span>
      </span>
    </figure>
  );
}

/** One drifting row; the list is rendered twice so the loop has no seam. */
function Row({
  items,
  reverse,
  render,
}: {
  items: FeaturedReview[];
  reverse: boolean;
  render: (r: FeaturedReview, copy: boolean) => React.ReactNode;
}) {
  return (
    <div
      className={`flex w-max gap-4 ${reverse ? "anim-marquee-reverse" : "anim-marquee"}`}
      style={{ ["--marquee-duration" as string]: `${String(items.length * 9)}s` }}
    >
      {items.map((r) => render(r, false))}
      {items.map((r) => render(r, true))}
    </div>
  );
}

/**
 * "Why people trust us": the overall rating, the two promises that back it (24/7
 * support, money back if a top-up is not credited), and a wall of real reviews —
 * each with its author, stars and the brand it was left for — drifting in two rows.
 * Renders the promises alone when the reviews cannot be read.
 */
export async function TrustReviews({ locale }: { locale: string }) {
  const t = await getTranslations("web.metrics");
  const data = await getFeaturedReviews(locale);
  const items = data?.items ?? [];
  const stats = data?.stats ?? null;
  const rating = stats && stats.count > 0 ? stats.avg : null;
  const fmt = new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 2 });

  const card = (r: FeaturedReview, copy: boolean) => (
    <div key={`${r.id}${copy ? "-copy" : ""}`} aria-hidden={copy || undefined} className="flex">
      <ReviewCard
        review={r}
        anonymous={t("anonymous")}
        starsLabel={t("stars", { rating: r.rating })}
      />
    </div>
  );
  const marquee = items.length >= MARQUEE_MIN;
  const half = Math.ceil(items.length / 2);

  return (
    <section className="py-14 sm:py-20">
      <div className="mx-auto max-w-[1280px] px-6 sm:px-10">
        <div className="text-primary font-mono text-xs font-semibold uppercase tracking-[0.16em]">
          [ 03 / {t("eyebrow")} ]
        </div>
        <h2 className="font-display mt-3 text-[clamp(1.9rem,3.5vw,3rem)] font-extrabold leading-[0.95] tracking-[-0.035em]">
          {t("title")}
        </h2>

        <div className="mt-8 grid grid-cols-1 gap-3 sm:grid-cols-3">
          {rating !== null && stats && (
            <div className="border-primary/30 bg-primary/[0.06] flex items-center gap-4 rounded-2xl border p-5">
              <span className="font-display text-primary text-5xl font-extrabold tracking-[-0.04em]">
                {fmt.format(rating)}
              </span>
              <span>
                <Stars
                  rating={Math.round(rating)}
                  label={t("stars", { rating: fmt.format(rating) })}
                />
                <span className="text-tx-mute mt-1 block text-[13px]">
                  {t("reviews", { count: stats.count })}
                </span>
              </span>
            </div>
          )}
          {(
            [
              ["support", Headphones],
              ["refund", ShieldCheck],
            ] as const
          ).map(([k, Icon]) => (
            <div
              key={k}
              className="border-border bg-card/60 flex items-center gap-4 rounded-2xl border p-5"
            >
              <span className="bg-primary/10 text-primary flex size-11 shrink-0 items-center justify-center rounded-xl">
                <Icon size={20} aria-hidden />
              </span>
              <span>
                <span className="block text-[15px] font-semibold">{t(`${k}Title`)}</span>
                <span className="text-tx-mute mt-0.5 block text-[13px]">{t(`${k}Note`)}</span>
              </span>
            </div>
          ))}
        </div>
      </div>

      {items.length > 0 &&
        (marquee ? (
          <div className="marquee-host mt-8 space-y-4 overflow-hidden [mask-image:linear-gradient(90deg,transparent,#000_8%,#000_92%,transparent)]">
            {/* Phones get one row with every review; wider screens two, drifting apart. */}
            <div className="sm:hidden">
              <Row items={items} reverse={false} render={card} />
            </div>
            <div className="hidden space-y-4 sm:block">
              <Row items={items.slice(0, half)} reverse={false} render={card} />
              <Row items={items.slice(half)} reverse render={card} />
            </div>
          </div>
        ) : (
          <div className="mx-auto mt-8 flex max-w-[1280px] gap-4 overflow-x-auto px-6 pb-2 sm:px-10">
            {items.map((r) => card(r, false))}
          </div>
        ))}
    </section>
  );
}
