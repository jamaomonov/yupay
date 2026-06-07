import { ArrowUpRight, Sparkles, Wallet, Zap } from "lucide-react";
import Image from "next/image";
import { getTranslations } from "next-intl/server";

import { buttonStyles } from "@/lib/button";
import { TELEGRAM_MINIAPP_URL } from "@/lib/links";

const FEATURES: { key: string; Icon: typeof Zap }[] = [
  { key: "f1", Icon: Zap },
  { key: "f2", Icon: Sparkles },
  { key: "f3", Icon: Wallet },
];

/**
 * "This is the real app" band — a contained dark panel with the YuPay mini
 * app shown as a three-screen podium (catalog · top-up · settings): a large
 * centre device flanked by two smaller ones, grounded by a lime stage-glow
 * and labelled per screen. Paired with three product bullets and a Telegram
 * CTA. Grounds the landing in the actual shipping product.
 */
export async function AppShowcase() {
  const t = await getTranslations("web.showcase");

  return (
    <section className="py-24">
      <div className="mx-auto max-w-[1280px] px-6 sm:px-10">
        <div className="border-border relative overflow-hidden rounded-2xl border bg-[radial-gradient(120%_120%_at_85%_0%,hsl(var(--card)),hsl(var(--bg))_60%)] px-6 py-14 sm:px-12 sm:py-16">
          {/* atmosphere */}
          <div aria-hidden className="pointer-events-none absolute inset-0">
            <div className="dot-cell absolute inset-0 opacity-[0.04]" />
            <div
              className="glow-lime absolute"
              style={{ width: 620, height: 620, right: "2%", top: "-12%" }}
            />
            <div
              className="glow-blue absolute"
              style={{ width: 460, height: 460, right: "30%", bottom: "-20%" }}
            />
          </div>

          <div className="relative grid grid-cols-1 items-center gap-12 lg:grid-cols-[0.9fr_1.1fr]">
            {/* ── LEFT: copy + features ── */}
            <div>
              <div className="text-primary font-mono text-xs font-semibold uppercase tracking-[0.16em]">
                [ 03 / {t("eyebrow")} ]
              </div>
              <h2 className="font-display mt-3 text-[clamp(2rem,3.8vw,3.2rem)] font-extrabold leading-[0.98] tracking-[-0.04em]">
                <span className="block">{t("titleLine1")}</span>
                <span className="text-primary block">{t("titleLine2")}</span>
              </h2>
              <p className="text-tx-mute mt-5 max-w-[440px] text-base leading-relaxed">
                {t("subtitle")}
              </p>

              <div className="mt-9 flex flex-col gap-3">
                {FEATURES.map(({ key, Icon }) => (
                  <div
                    key={key}
                    className="border-border/70 bg-card/40 hover:border-primary/30 hover:bg-card/70 flex items-start gap-4 rounded-2xl border p-4 transition"
                  >
                    <span className="border-primary/25 bg-primary/10 mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] border">
                      <Icon size={18} className="text-primary" />
                    </span>
                    <div>
                      <div className="font-display text-[16px] font-bold tracking-[-0.01em]">
                        {t(`${key}Title`)}
                      </div>
                      <p className="text-tx-mute mt-1 max-w-[380px] text-sm leading-relaxed">
                        {t(`${key}Sub`)}
                      </p>
                    </div>
                  </div>
                ))}
              </div>

              <a
                href={TELEGRAM_MINIAPP_URL}
                target="_blank"
                rel="noreferrer noopener"
                className={buttonStyles({ size: "lg", className: "group mt-9" })}
              >
                {t("cta")}
                <ArrowUpRight size={17} strokeWidth={2.6} />
              </a>
            </div>

            {/* ── RIGHT: three-screen podium ── */}
            <div className="relative mx-auto h-[460px] w-full max-w-[620px] sm:h-[540px]">
              {/* stage glow grounding the devices */}
              <div
                aria-hidden
                className="absolute left-1/2 top-[40%] -translate-x-1/2"
                style={{
                  width: 460,
                  height: 460,
                  background:
                    "radial-gradient(circle, hsl(var(--primary) / 0.16), transparent 62%)",
                  filter: "blur(50px)",
                }}
              />

              {/* left — catalog */}
              <div className="anim-float-slow absolute left-0 top-[16%] z-10 w-[42%]">
                <Image
                  src="/mockups/home.png"
                  alt="Экран каталога приложения yupay"
                  width={2000}
                  height={1964}
                  sizes="(max-width: 1024px) 38vw, 250px"
                  className="h-auto w-full opacity-90 drop-shadow-[0_28px_55px_rgba(0,0,0,0.55)]"
                />
              </div>

              {/* right — settings */}
              <div className="anim-float-slow absolute right-0 top-[11%] z-20 w-[44%]">
                <Image
                  src="/mockups/settings.png"
                  alt="Экран настроек приложения yupay"
                  width={2000}
                  height={1964}
                  sizes="(max-width: 1024px) 40vw, 260px"
                  className="h-auto w-full opacity-95 drop-shadow-[0_28px_55px_rgba(0,0,0,0.55)]"
                />
              </div>

              {/* centre — top-up (hero of the trio) */}
              <div className="absolute left-1/2 top-0 z-30 w-[52%] -translate-x-1/2">
                <Image
                  src="/mockups/topup.png"
                  alt="Экран пополнения PUBG Mobile в приложении yupay"
                  width={2000}
                  height={1964}
                  sizes="(max-width: 1024px) 50vw, 320px"
                  className="h-auto w-full drop-shadow-[0_40px_80px_rgba(0,0,0,0.7)]"
                />
              </div>

              {/* per-screen labels */}
              <div className="absolute inset-x-0 bottom-0 z-40 flex flex-wrap items-center justify-center gap-2">
                {[t("labelCatalog"), t("labelTopup"), t("labelSettings")].map((label, i) => (
                  <span
                    key={label}
                    className={`border-border-2/70 bg-card/80 inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 font-mono text-[11px] font-semibold backdrop-blur-md ${
                      i === 1 ? "text-primary" : "text-tx-mute"
                    }`}
                  >
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${i === 1 ? "bg-primary" : "bg-tx-dim"}`}
                    />
                    {label}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
