import { LayoutGrid, Package, Settings, Check, type LucideIcon } from "lucide-react";

/** The cabinet words the picture repeats, translated by the caller. */
export interface CabinetMockLabels {
  catalog: string;
  orders: string;
  settings: string;
  account: string;
  delivered: string;
}

/**
 * The six tiles, each with the brand's own square art.
 *
 * The files are **ours and local** — pulled once from `GET /catalog/brands`
 * and squared down to 64px — rather than fetched at render. This figure is a
 * drawing, and a drawing that makes six CDN requests above the fold is a
 * drawing that can arrive half-empty on the slowest connection it is meant to
 * impress. A brand whose logo changes is a file to refresh here, which is the
 * right trade for the one illustration on the site.
 *
 * Brand names are the same in every locale, so they stay out of the catalogs.
 */
const TILES: { name: string; art: string }[] = [
  { name: "PUBG Mobile", art: "/brands/pubg-mobile.png" },
  { name: "Mobile Legends", art: "/brands/mobile-legends.png" },
  { name: "Free Fire", art: "/brands/free-fire.png" },
  { name: "Roblox", art: "/brands/roblox.png" },
  { name: "Steam", art: "/brands/steam.png" },
  { name: "Discord", art: "/brands/discord.png" },
];

/** The sidebar, with the icons each of those screens actually carries. */
const NAV: { key: keyof CabinetMockLabels; icon: LucideIcon }[] = [
  { key: "catalog", icon: LayoutGrid },
  { key: "orders", icon: Package },
  { key: "settings", icon: Settings },
];

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
 * The sidebar icons are the ones those screens really carry (`Shell.tsx` and
 * the catalog's own empty state), so the picture stays a picture of the
 * product rather than of something adjacent to it.
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
        {/* The window controls, in their real colours. Three identical grey
            dots read as a loading placeholder as readily as a title bar; the
            traffic light is the one piece of chrome everybody parses without
            looking at it, and it is what says "this is an application". */}
        <div className="border-border flex items-center gap-1.5 border-b px-4 py-3">
          <span className="bg-danger h-2.5 w-2.5 rounded-full" />
          <span className="bg-gold h-2.5 w-2.5 rounded-full" />
          <span className="bg-primary h-2.5 w-2.5 rounded-full" />
        </div>

        {/* 7rem, and the labels wrap rather than truncate: these three words
            are the longest in Uzbek — «Buyurtmalar», «Sozlamalar» — and a
            picture of the product that cuts the product's own nav labels in
            half is worse than one that lets a word wrap. */}
        <div className="grid grid-cols-[7rem_1fr]">
          <nav className="border-border text-tx-dim space-y-1 border-r p-2.5 text-[10.5px]">
            {NAV.map(({ key, icon: Icon }) => (
              <p
                key={key}
                className={`flex items-center gap-1.5 rounded-md px-2 py-1 leading-tight ${
                  key === "catalog" ? "text-primary-ink bg-muted font-semibold" : ""
                }`}
              >
                <Icon size={12} className="shrink-0" strokeWidth={2} />
                <span className="min-w-0">{labels[key]}</span>
              </p>
            ))}
          </nav>

          <div className="p-3">
            <div className="grid grid-cols-3 gap-2">
              {TILES.map(({ name, art }) => (
                <div
                  key={name}
                  className="border-border bg-card-2 text-tx-mute flex items-center gap-1 rounded-lg border px-1.5 py-2 text-[10px] leading-tight"
                >
                  <Art src={art} size={16} />
                  <span className="min-w-0">{name}</span>
                </div>
              ))}
            </div>

            <div className="border-border bg-card-2 mt-3 rounded-xl border p-3">
              <p className="flex items-center gap-2 text-[11.5px] font-semibold">
                <Art src={TILES[0]?.art ?? ""} size={20} />
                {TILES[0]?.name}
              </p>
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

/**
 * One square piece of brand art.
 *
 * A plain `<img>`, not `next/image`: these are six decorative 64px files we
 * ship ourselves, inside a figure that is already `aria-hidden`, and routing
 * them through the optimizer would trade a static asset for a request per
 * tile to save nothing. `width`/`height` are on the element so the tiles do
 * not reflow while the art loads.
 */
function Art({ src, size }: { src: string; size: number }) {
  return (
    /* eslint-disable-next-line @next/next/no-img-element --
       see the note above: a local decorative asset at a fixed pixel size. */
    <img
      src={src}
      alt=""
      width={size}
      height={size}
      className="shrink-0 rounded-[5px] object-cover"
      style={{ width: size, height: size }}
    />
  );
}
