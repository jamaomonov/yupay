import { BadgeCheck, Clock, MessageCircle, ShieldCheck } from "lucide-react";
import { getTranslations } from "next-intl/server";

const ITEMS = [
  { Icon: Clock, key: "speed" },
  { Icon: ShieldCheck, key: "noPassword" },
  { Icon: BadgeCheck, key: "guarantee" },
  { Icon: MessageCircle, key: "support" },
] as const;

/**
 * Reassurance strip — surfaces the guarantees that otherwise only live in the
 * legal pages (delivery speed, no password handover, money-back if we fail to
 * deliver, human support) right where they drive conversion. The support tile
 * links straight to the Telegram support handle.
 */
export async function TrustBand() {
  const t = await getTranslations("web.trust");
  return (
    <section className="border-border/60 border-y">
      <div className="mx-auto grid max-w-[1200px] grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
        {ITEMS.map(({ Icon, key }, i) => {
          const inner = (
            <div className="flex h-full items-start gap-3.5 px-6 py-6 sm:px-8">
              <Icon size={22} strokeWidth={2.2} className="text-primary mt-0.5 shrink-0" />
              <div>
                <div className="text-[15px] font-semibold tracking-[-0.01em]">
                  {t(`${key}.title`)}
                </div>
                <div className="text-tx-mute mt-0.5 text-[13px] leading-relaxed">
                  {t(`${key}.sub`)}
                </div>
              </div>
            </div>
          );
          const border = i > 0 ? "border-border/60 sm:border-l" : "";
          const lgBorder = i % 4 === 0 ? "lg:border-l-0" : "lg:border-l";
          const topBorder = i > 0 ? "border-border/60 border-t sm:border-t-0" : "";
          return key === "support" ? (
            <a
              key={key}
              href="https://t.me/yupay_support"
              target="_blank"
              rel="noreferrer noopener"
              className={`hover:bg-muted/40 transition ${border} ${lgBorder} ${topBorder}`}
            >
              {inner}
            </a>
          ) : (
            <div key={key} className={`${border} ${lgBorder} ${topBorder}`}>
              {inner}
            </div>
          );
        })}
      </div>
    </section>
  );
}
