import { Zap } from "lucide-react";

const ITEMS = [
  "STEAM",
  "PUBG MOBILE",
  "FREE FIRE",
  "GENSHIN IMPACT",
  "DELTA FORCE",
  "ARENA BREAKOUT",
];

/**
 * Marquee strip beneath the hero — names of the most popular services
 * scrolling left. Doubled inline so the loop has no visible seam. Brand
 * names are constants (Steam / PUBG / etc.) — no i18n needed.
 */
export function Ticker() {
  const track = [...ITEMS, ...ITEMS];
  return (
    <div className="border-border bg-muted/30 flex h-16 items-center overflow-hidden border-y">
      <div className="anim-ticker flex w-max gap-10 whitespace-nowrap pl-10">
        {track.map((label, i) => (
          <span
            key={i}
            className="font-display text-foreground inline-flex items-center gap-3.5 text-[22px] font-extrabold tracking-[-0.02em]"
          >
            {label}
            <Zap size={14} className="fill-primary text-primary" strokeWidth={0} />
          </span>
        ))}
      </div>
    </div>
  );
}
