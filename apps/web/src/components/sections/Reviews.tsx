import { Star } from "lucide-react";
import { getTranslations } from "next-intl/server";

type Review = {
  key: string;
  initial: string;
  avBg: string;
};

const REVIEWS: Review[] = [
  { key: "alex", initial: "A", avBg: "linear-gradient(135deg,#5BA8FF,#1B2838)" },
  { key: "mage", initial: "M", avBg: "linear-gradient(135deg,#9D5BFF,#2a1340)" },
  { key: "vova", initial: "V", avBg: "linear-gradient(135deg,#FF4655,#6e1a23)" },
  { key: "chicken", initial: "i", avBg: "linear-gradient(135deg,#FFAA00,#1a1a1a)" },
  { key: "zero", initial: "Z", avBg: "linear-gradient(135deg,#4FB4E0,#2A8CC2)" },
];

function Stars({ size = 13 }: { size?: number }) {
  return (
    <div className="flex gap-[2px]">
      {Array.from({ length: 5 }).map((_, i) => (
        <Star key={i} size={size} className="fill-gold text-gold" />
      ))}
    </div>
  );
}

/**
 * Social-proof grid — one large featured review + four smaller ones.
 * 1.4fr / 1fr / 1fr columns to match the design ref; the featured card
 * spans two rows and gets a lime-tinted gradient + a larger pull-quote.
 */
export async function Reviews() {
  const t = await getTranslations("web.reviews");
  const [featured, ...rest] = REVIEWS;
  if (!featured) return null;

  return (
    <section id="reviews" className="py-24">
      <div className="mx-auto max-w-[1200px] px-6 sm:px-10">
        <div className="mb-14 flex flex-wrap items-end justify-between gap-6">
          <div>
            <div className="font-mono text-xs font-semibold uppercase tracking-[0.16em] text-primary">
              [ 04 / {t("eyebrow")} ]
            </div>
            <h2 className="mt-3 font-display text-[clamp(2.2rem,4vw,3.4rem)] font-extrabold leading-[0.98] tracking-[-0.04em]">
              <span className="block">{t("titleLine1")}</span>
              <span className="block">{t("titleLine2")}</span>
            </h2>
          </div>
          <div className="flex items-center gap-3">
            <Stars size={20} />
            <span className="font-display text-[28px] font-bold tracking-[-0.02em]">
              {t("score")}
            </span>
            <span className="text-sm text-tx-mute">{t("reviewCount")}</span>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-5 md:grid-cols-[1.4fr_1fr_1fr] md:grid-rows-2">
          <ReviewCard
            featured
            quote={t(`${featured.key}.quote`)}
            name={t(`${featured.key}.name`)}
            meta={t(`${featured.key}.meta`)}
            initial={featured.initial}
            avBg={featured.avBg}
          />
          {rest.map((r) => (
            <ReviewCard
              key={r.key}
              quote={t(`${r.key}.quote`)}
              name={t(`${r.key}.name`)}
              meta={t(`${r.key}.meta`)}
              initial={r.initial}
              avBg={r.avBg}
            />
          ))}
        </div>
      </div>
    </section>
  );
}

function ReviewCard({
  featured = false,
  quote,
  name,
  meta,
  initial,
  avBg,
}: {
  featured?: boolean;
  quote: string;
  name: string;
  meta: string;
  initial: string;
  avBg: string;
}) {
  return (
    <div
      className={`flex flex-col justify-between gap-6 rounded-[20px] border ${
        featured
          ? "border-primary/20 bg-[linear-gradient(135deg,hsl(var(--primary)/0.06),hsl(var(--card)))] p-9 md:row-span-2"
          : "border-border bg-card p-6"
      }`}
    >
      <div>
        <Stars size={featured ? 16 : 13} />
        <p
          className={`mt-4 font-display font-medium tracking-[-0.005em] text-foreground ${
            featured ? "text-2xl leading-snug tracking-[-0.015em]" : "text-[15px] leading-snug"
          }`}
        >
          «{quote}»
        </p>
      </div>
      <div className="flex items-center gap-3">
        <div
          className="flex h-10 w-10 items-center justify-center rounded-full font-display font-extrabold text-white"
          style={{ background: avBg }}
        >
          {initial}
        </div>
        <div>
          <div className={`font-bold ${featured ? "text-base" : "text-[13px]"}`}>{name}</div>
          <div className={`text-tx-mute ${featured ? "text-xs" : "text-[11px]"}`}>{meta}</div>
        </div>
      </div>
    </div>
  );
}
