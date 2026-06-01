import { getTranslations } from "next-intl/server";

const METRICS: { key: string; value: string; suffix?: string; lime?: boolean }[] = [
  { key: "totalOrders", value: "100", suffix: "K+" },
  { key: "avgTime", value: "1:47", lime: true },
  { key: "supportReply", value: "30", suffix: "сек" },
];

/**
 * Numbers band — rounded card with a faint grid overlay. Lays the trust
 * proof out as three big monospaced numerals with paired labels + sub-notes.
 * Headline + ‟updated at" timestamp wrap above the grid.
 */
export async function MetricsBand() {
  const t = await getTranslations("web.metrics");

  return (
    <section className="py-28">
      <div className="mx-auto max-w-[1280px] px-6 sm:px-10">
        <div className="border-border relative overflow-hidden rounded-2xl border bg-[linear-gradient(135deg,hsl(var(--muted)/0.6),hsl(var(--card)/0.4))] p-10 sm:p-16">
          <div
            aria-hidden
            className="absolute inset-0 opacity-100"
            style={{
              backgroundImage:
                "linear-gradient(hsl(var(--primary) / 0.02) 1px, transparent 1px), linear-gradient(90deg, hsl(var(--primary) / 0.02) 1px, transparent 1px)",
              backgroundSize: "40px 40px",
            }}
          />
          <div className="relative mb-12">
            <div className="text-primary font-mono text-xs font-semibold uppercase tracking-[0.16em]">
              [ 03 / {t("eyebrow")} ]
            </div>
            <h2 className="font-display mt-3 text-[clamp(1.9rem,3.5vw,3rem)] font-extrabold leading-[0.95] tracking-[-0.035em]">
              {t("title")}
            </h2>
          </div>

          <div className="relative grid grid-cols-1 gap-8 sm:grid-cols-3">
            {METRICS.map((m) => (
              <div key={m.key} className="border-border-2 border-t pt-6">
                <div
                  className={`font-display flex items-baseline text-[clamp(3rem,6vw,5rem)] font-extrabold leading-[0.9] tracking-[-0.05em] ${
                    m.lime ? "text-primary" : "text-foreground"
                  }`}
                >
                  {m.value}
                  {m.suffix && (
                    <span className="text-tx-mute ml-1 text-[clamp(1.4rem,2.5vw,2rem)] font-bold">
                      {m.suffix}
                    </span>
                  )}
                </div>
                <div className="mt-3 text-sm font-semibold tracking-[-0.01em]">
                  {t(`${m.key}Label`)}
                </div>
                <div className="text-tx-mute mt-1 text-xs">{t(`${m.key}Note`)}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
