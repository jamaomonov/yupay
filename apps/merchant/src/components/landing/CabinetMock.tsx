import { Check } from "lucide-react";

/** The cabinet words the picture repeats, translated by the caller. */
export interface CabinetMockLabels {
  catalog: string;
  orders: string;
  settings: string;
  account: string;
  delivered: string;
}

/** Brand names are the same in every locale, so they stay out of the catalogs. */
const TILES = ["PUBG Mobile", "Mobile Legends", "Free Fire", "Roblox", "Steam", "Discord"] as const;

/**
 * A drawing of the cabinet, in place of the JSON window that used to open this
 * page.
 *
 * It answers "what will I actually be using" for the audience that does not
 * write code, and it is a drawing and nothing else: no fetch, no prices, no
 * counts. A mock-up that shows numbers is read as a claim about the catalog,
 * and a claim nobody updates is a lie by the time the catalog moves — which is
 * why `countBrands()` exists for the one number on this page and why there is
 * not a second source of them here.
 *
 * `aria-hidden` on the whole figure, with a caption that only a screen reader
 * gets: read aloud, a fake sidebar and six brand tiles are noise, but silence
 * about the illustration is worse than one sentence naming it.
 */
export function CabinetMock({ labels, caption }: { labels: CabinetMockLabels; caption: string }) {
  return (
    <figure className="m-0">
      <figcaption className="sr-only">{caption}</figcaption>
      <div
        aria-hidden="true"
        className="border-border bg-card select-none overflow-hidden rounded-2xl border shadow-sm"
      >
        <div className="border-border flex items-center gap-1.5 border-b px-4 py-3">
          <span className="bg-border-2 h-2 w-2 rounded-full" />
          <span className="bg-border-2 h-2 w-2 rounded-full" />
          <span className="bg-border-2 h-2 w-2 rounded-full" />
        </div>

        <div className="grid grid-cols-[6.5rem_1fr]">
          <nav className="border-border text-tx-dim space-y-1.5 border-r p-3 text-[11px]">
            <p className="text-primary-ink bg-muted rounded-md px-2 py-1 font-semibold">
              {labels.catalog}
            </p>
            <p className="px-2 py-1">{labels.orders}</p>
            <p className="px-2 py-1">{labels.settings}</p>
          </nav>

          <div className="p-3">
            <div className="grid grid-cols-3 gap-2">
              {TILES.map((tile) => (
                <div
                  key={tile}
                  className="border-border bg-card-2 text-tx-mute rounded-lg border px-2 py-3 text-center text-[10.5px] leading-tight"
                >
                  {tile}
                </div>
              ))}
            </div>

            <div className="border-border bg-card-2 mt-3 rounded-xl border p-3">
              <p className="text-[11.5px] font-semibold">{TILES[0]}</p>
              {/* The ID field, mid-check: the line below is the whole reason
                  this card is in the picture. */}
              <div className="border-border text-tx-dim mt-2 rounded-lg border px-2.5 py-2 font-mono text-[11px] tracking-[0.3em]">
                ••••••••
              </div>
              <p className="text-primary-ink mt-2 flex items-center gap-1.5 text-[11px] font-semibold">
                <Check size={13} />
                {labels.account}: Neo_Uz
              </p>
              <p className="mt-3">
                <span className="border-border text-primary-ink rounded-full border px-2.5 py-1 text-[10.5px] font-bold tracking-[0.04em]">
                  {labels.delivered}
                </span>
              </p>
            </div>
          </div>
        </div>
      </div>
    </figure>
  );
}
