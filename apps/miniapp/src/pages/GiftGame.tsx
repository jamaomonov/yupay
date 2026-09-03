import { motion } from "framer-motion";
import { ArrowLeft, Check, ChevronLeft, ChevronRight, HelpCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useParams } from "wouter";

import type { GiftApp, GiftAppDetail, GiftPackage } from "@/lib/gifts";

import { SafeImage } from "@/components/ui/safe-image";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { formatMoney } from "@/lib/currency";
import { fetchGiftDetail, fetchGiftDlc, priceFor, validateInviteUrl } from "@/lib/gifts";
import { useT } from "@/lib/i18n";
import { haptic } from "@/lib/telegram";
import { useDocumentTitle } from "@/lib/use-document-title";

/** How many offered zones show as their own pill before the rest collapse
 *  behind a single "другой регион" toggle — mirrors the web panel's
 *  `VISIBLE_ZONE_COUNT`. */
const VISIBLE_ZONE_COUNT = 4;
/** Matches the API's default DLC page size (`gifts/routes.py`). */
const DLC_PAGE_SIZE = 24;
const DLC_SEARCH_DEBOUNCE_MS = 400;

/**
 * Region kept after an edition/package switch: the current zone if the new
 * package still prices it, else the app's default zone, else whatever price
 * the package does offer, else — a package with no prices at all — the zone
 * is left untouched. Mirrors `GiftPurchasePanel.tsx::selectPackage` on the
 * web storefront exactly.
 */
export function zoneAfterPackageChange(
  pkg: GiftPackage,
  currentZone: string,
  defaultZone: string,
): string {
  if (pkg.prices.some((p) => p.zone === currentZone)) return currentZone;
  const fallback = pkg.prices.find((p) => p.zone === defaultZone) ?? pkg.prices[0];
  return fallback ? fallback.zone : currentZone;
}

/** Splits an app's offered zones into the pills shown up front and the ones
 *  collapsed behind "другой регион". */
export function splitZones(
  zones: string[],
  visibleCount: number,
): { visible: string[]; overflow: string[] } {
  return { visible: zones.slice(0, visibleCount), overflow: zones.slice(visibleCount) };
}

function priceLabel(price: { price_usd: string; price_uzs: string | null } | null): string {
  if (!price) return "—";
  return price.price_uzs != null
    ? formatMoney(Math.round(Number(price.price_uzs)), "UZS")
    : formatMoney(Number(price.price_usd), "USD");
}

// ─── Edition (package) picker ───────────────────────────────────────────────
function PackageOption({
  pkg,
  price,
  active,
  onSelect,
}: {
  pkg: GiftPackage;
  price: { price_usd: string; price_uzs: string | null } | null;
  active: boolean;
  onSelect: () => void;
}) {
  const discount =
    pkg.discount_percent != null && pkg.discount_percent > 0 ? pkg.discount_percent : null;
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onSelect}
      className="relative rounded-2xl p-3.5 text-left transition-all duration-150"
      style={{
        background: active ? "hsl(var(--surface-3))" : "hsl(var(--surface-2))",
        border: active ? "1.5px solid hsl(var(--primary) / 0.8)" : "1px solid hsl(var(--border))",
      }}
    >
      {active && (
        <div
          className="absolute right-2.5 top-2.5 flex h-5 w-5 items-center justify-center rounded-full"
          style={{ background: "hsl(var(--primary))" }}
        >
          <Check size={11} strokeWidth={3} className="text-black" />
        </div>
      )}
      <div className="flex items-center justify-between gap-3 pr-6">
        <span className="text-sm font-bold text-white">{pkg.name}</span>
        <span className="font-mono text-sm font-bold tabular-nums text-white">
          {priceLabel(price)}
        </span>
      </div>
      {discount !== null && (
        <span className="text-primary mt-1 inline-block text-[11px] font-bold">-{discount}%</span>
      )}
    </button>
  );
}

// ─── Region pill ─────────────────────────────────────────────────────────────
function ZonePill({
  zone,
  active,
  available,
  onSelect,
}: {
  zone: string;
  active: boolean;
  available: boolean;
  onSelect: () => void;
}) {
  const { t } = useT();
  return (
    <button
      type="button"
      disabled={!available}
      title={available ? undefined : t("gifts.game.noPriceInRegion")}
      aria-pressed={active}
      onClick={onSelect}
      className="rounded-full border px-3 py-1.5 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-40"
      style={{
        borderColor: active ? "hsl(var(--primary))" : "hsl(var(--border))",
        background: active ? "hsl(var(--primary) / 0.12)" : "transparent",
        color: active ? "hsl(var(--primary))" : "rgba(255,255,255,0.6)",
      }}
    >
      {zone}
    </button>
  );
}

// ─── "Где найти ссылку?" guide sheet ────────────────────────────────────────
function InviteGuideSheet({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const { t } = useT();
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="bottom" className="rounded-t-3xl">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <HelpCircle size={16} className="text-primary" aria-hidden="true" />
            {t("gifts.game.inviteGuideTitle")}
          </SheetTitle>
          <SheetDescription asChild>
            <ol className="mt-1 list-decimal space-y-1.5 pl-5 text-left leading-relaxed text-white/70">
              <li>{t("gifts.game.inviteGuideStep1")}</li>
              <li>{t("gifts.game.inviteGuideStep2")}</li>
              <li>{t("gifts.game.inviteGuideStep3")}</li>
            </ol>
          </SheetDescription>
        </SheetHeader>
      </SheetContent>
    </Sheet>
  );
}

// ─── DLC browser sheet ───────────────────────────────────────────────────────
type DlcPhase = "idle" | "loading" | "error";

function DlcSheet({
  open,
  onOpenChange,
  appId,
  total,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  appId: number;
  total: number;
}) {
  const { t } = useT();
  const [raw, setRaw] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<GiftApp[]>([]);
  const [resultTotal, setResultTotal] = useState(total);
  const [phase, setPhase] = useState<DlcPhase>("idle");
  const seqRef = useRef(0);

  function fetchPage(nextOffset: number, forQuery: string): void {
    const seq = ++seqRef.current;
    setPhase("loading");
    fetchGiftDlc(appId, forQuery, nextOffset)
      .then((page) => {
        if (seq !== seqRef.current) return;
        setItems(page.items);
        setResultTotal(page.total);
        setOffset(nextOffset);
        setPhase("idle");
      })
      .catch(() => {
        if (seq !== seqRef.current) return;
        setPhase("error");
      });
  }

  // Fresh mount each time the sheet opens — load the unfiltered first page.
  useEffect(() => {
    if (!open) return;
    setRaw("");
    setQuery("");
    fetchPage(0, "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, appId]);

  useEffect(() => {
    if (!open) return;
    const timer = setTimeout(() => {
      setQuery(raw.trim());
    }, DLC_SEARCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [raw, open]);

  const isFirstRun = useRef(true);
  useEffect(() => {
    if (!open) return;
    if (isFirstRun.current) {
      isFirstRun.current = false;
      return;
    }
    fetchPage(0, query);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  const canPrev = offset > 0;
  const canNext = offset + DLC_PAGE_SIZE < resultTotal;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="bottom" className="max-h-[80vh] overflow-y-auto rounded-t-3xl">
        <SheetHeader>
          <SheetTitle>{t("gifts.dlc.toggle", { count: total })}</SheetTitle>
        </SheetHeader>
        <input
          type="search"
          value={raw}
          onChange={(e) => {
            setRaw(e.target.value);
          }}
          placeholder={t("gifts.dlc.searchPlaceholder")}
          aria-label={t("gifts.dlc.searchPlaceholder")}
          className="mt-3 h-10 w-full rounded-xl border bg-transparent px-3 text-sm text-white outline-none"
          style={{ borderColor: "hsl(var(--border))" }}
        />

        {phase === "error" ? (
          <div className="mt-6 flex flex-col items-center gap-2 text-center">
            <p className="text-sm text-white/50">{t("gifts.search.error")}</p>
            <button
              type="button"
              onClick={() => {
                fetchPage(offset, query);
              }}
              className="text-primary text-sm font-semibold"
            >
              {t("common.retry")}
            </button>
          </div>
        ) : phase === "loading" ? (
          <div className="mt-4 grid grid-cols-2 gap-3">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="aspect-[16/9] rounded-xl" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <p className="mt-6 text-center text-sm text-white/50">{t("gifts.search.empty")}</p>
        ) : (
          <div className="mt-4 grid grid-cols-2 gap-3">
            {items.map((app) => (
              <Link
                key={app.app_id}
                href={`/gifts/${String(app.app_id)}`}
                onClick={() => {
                  onOpenChange(false);
                }}
                className="flex flex-col overflow-hidden rounded-xl border"
                style={{ borderColor: "hsl(var(--border))" }}
              >
                <div className="aspect-[16/9] w-full overflow-hidden bg-black/20">
                  {app.image && (
                    <SafeImage src={app.image} className="h-full w-full object-cover" />
                  )}
                </div>
                <p className="line-clamp-2 p-2 text-[12px] font-semibold text-white">{app.name}</p>
              </Link>
            ))}
          </div>
        )}

        {phase === "idle" && items.length > 0 && (canPrev || canNext) && (
          <div className="mt-4 flex items-center justify-center gap-3">
            <button
              type="button"
              disabled={!canPrev}
              onClick={() => {
                fetchPage(offset - DLC_PAGE_SIZE, query);
              }}
              aria-label={t("gifts.dlc.prevPage")}
              className="flex h-8 w-8 items-center justify-center rounded-full disabled:opacity-30"
              style={{ background: "hsl(var(--surface-2))" }}
            >
              <ChevronLeft size={16} className="text-white/70" />
            </button>
            <button
              type="button"
              disabled={!canNext}
              onClick={() => {
                fetchPage(offset + DLC_PAGE_SIZE, query);
              }}
              aria-label={t("gifts.dlc.nextPage")}
              className="flex h-8 w-8 items-center justify-center rounded-full disabled:opacity-30"
              style={{ background: "hsl(var(--surface-2))" }}
            >
              <ChevronRight size={16} className="text-white/70" />
            </button>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────
type Phase = "loading" | "idle" | "error" | "notFound";

export default function GiftGame() {
  const { t } = useT();
  const { appId } = useParams<{ appId: string }>();
  const [, setLocation] = useLocation();

  const numericAppId = Number(appId);
  const validAppId = Number.isInteger(numericAppId) && numericAppId > 0;

  const [detail, setDetail] = useState<GiftAppDetail | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [selectedPackageId, setSelectedPackageId] = useState<number | null>(null);
  const [selectedZone, setSelectedZone] = useState<string | null>(null);
  const [inviteUrl, setInviteUrl] = useState("");
  const [guideOpen, setGuideOpen] = useState(false);
  const [dlcOpen, setDlcOpen] = useState(false);
  const [zoneExpanded, setZoneExpanded] = useState(false);
  const seqRef = useRef(0);

  function load(): void {
    if (!validAppId) {
      setPhase("notFound");
      return;
    }
    const seq = ++seqRef.current;
    setPhase("loading");
    fetchGiftDetail(numericAppId)
      .then((d) => {
        if (seq !== seqRef.current) return;
        if (!d) {
          setDetail(null);
          setPhase("notFound");
          return;
        }
        setDetail(d);
        setSelectedPackageId(d.packages[0]?.id ?? null);
        setSelectedZone(d.zone_default);
        setZoneExpanded(false);
        setPhase("idle");
      })
      .catch(() => {
        if (seq !== seqRef.current) return;
        setPhase("error");
      });
  }

  useEffect(() => {
    load();
    // Re-fetch whenever the route's appId changes (a DLC link navigates
    // in-place, this page doesn't unmount/remount for it).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appId]);

  useDocumentTitle(
    detail ? t("gifts.game.docTitleNamed", { name: detail.name }) : t("gifts.docTitle"),
  );

  const selectedPackage =
    detail?.packages.find((p) => p.id === selectedPackageId) ?? detail?.packages[0] ?? null;
  const price = priceFor(detail, selectedPackage?.id ?? null, selectedZone);

  function selectPackage(pkg: GiftPackage): void {
    haptic("select");
    setSelectedPackageId(pkg.id);
    if (!detail) return;
    setSelectedZone((current) =>
      zoneAfterPackageChange(pkg, current ?? detail.zone_default, detail.zone_default),
    );
  }

  function selectZone(zone: string): void {
    if (!selectedPackage?.prices.some((p) => p.zone === zone)) return;
    haptic("select");
    setSelectedZone(zone);
  }

  const canonicalInvite = validateInviteUrl(inviteUrl);
  const inviteTouched = inviteUrl.trim() !== "";
  const canBuy = price !== null && canonicalInvite !== null;

  function handleBuy(): void {
    // Wired in the checkout commit (Task M2) — the package/zone/invite state
    // collected above already matches what that commit's checkout body needs.
  }

  if (phase === "loading") {
    return (
      <div className="pb-32">
        <Skeleton className="h-56 w-full" />
        <div className="space-y-4 px-4 pt-5">
          <Skeleton className="h-6 w-2/3" />
          <Skeleton className="h-16 w-full rounded-2xl" />
          <div className="grid grid-cols-2 gap-2.5">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-16 rounded-2xl" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (phase === "notFound" || !detail) {
    return (
      <div className="flex flex-col items-center gap-4 p-6 pt-24 text-center">
        <h2 className="text-xl font-bold text-white">{t("gifts.game.notFound")}</h2>
        <button
          type="button"
          onClick={() => {
            setLocation("/gifts");
          }}
          className="bg-primary rounded-2xl px-6 py-3 font-bold text-black"
        >
          {t("common.toHome")}
        </button>
      </div>
    );
  }

  if (phase === "error") {
    return (
      <div className="flex flex-col items-center gap-4 p-6 pt-24 text-center">
        <p className="text-sm text-white/50">{t("gifts.search.error")}</p>
        <button
          type="button"
          onClick={load}
          className="bg-primary rounded-2xl px-6 py-3 font-bold text-black"
        >
          {t("common.retry")}
        </button>
      </div>
    );
  }

  const { visible: visibleZones, overflow: overflowZones } = splitZones(
    detail.zones,
    VISIBLE_ZONE_COUNT,
  );

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.22 }}
      className="pb-32"
    >
      <InviteGuideSheet open={guideOpen} onOpenChange={setGuideOpen} />
      <DlcSheet
        open={dlcOpen}
        onOpenChange={setDlcOpen}
        appId={detail.app_id}
        total={detail.dlc_total}
      />

      {/* ── Hero ── */}
      <div className="relative h-56 overflow-hidden">
        {detail.image ? (
          <SafeImage
            src={detail.image}
            className="absolute inset-0 h-full w-full object-cover"
            fallback={
              <div className="absolute inset-0 bg-gradient-to-br from-slate-800 to-slate-950" />
            }
          />
        ) : (
          <div className="absolute inset-0 bg-gradient-to-br from-slate-800 to-slate-950" />
        )}
        <div className="from-background via-background/40 absolute inset-0 bg-gradient-to-t to-black/20" />
        <button
          type="button"
          onClick={() => {
            setLocation("/gifts");
          }}
          aria-label={t("common.back")}
          className="absolute left-4 top-12 z-20 flex h-9 w-9 items-center justify-center rounded-full bg-black/40 backdrop-blur-sm"
        >
          <ArrowLeft size={16} className="text-white" />
        </button>
        <div className="absolute bottom-0 left-0 right-0 z-10 px-4 pb-4">
          <h1 className="line-clamp-2 text-lg font-bold leading-tight text-white">{detail.name}</h1>
        </div>
      </div>

      <div className="space-y-6 px-4 pt-5">
        {detail.description && (
          <p className="text-sm leading-relaxed text-white/55">{detail.description}</p>
        )}

        {detail.dlc_total > 0 && (
          <button
            type="button"
            onClick={() => {
              setDlcOpen(true);
            }}
            className="text-primary text-sm font-semibold"
          >
            {t("gifts.dlc.toggle", { count: detail.dlc_total })}
          </button>
        )}

        {/* Step: edition */}
        <div>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-white/50">
            {t("gifts.game.edition")}
          </p>
          <div className="flex flex-col gap-2">
            {detail.packages.map((pkg) => (
              <PackageOption
                key={pkg.id}
                pkg={pkg}
                price={selectedZone ? (priceFor(detail, pkg.id, selectedZone) ?? null) : null}
                active={pkg.id === selectedPackage?.id}
                onSelect={() => {
                  selectPackage(pkg);
                }}
              />
            ))}
          </div>
        </div>

        {/* Step: region */}
        <div>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-white/50">
            {t("gifts.game.region")}
          </p>
          <div className="flex flex-wrap gap-2">
            {visibleZones.map((zone) => (
              <ZonePill
                key={zone}
                zone={zone}
                active={zone === selectedZone}
                available={selectedPackage?.prices.some((p) => p.zone === zone) ?? false}
                onSelect={() => {
                  selectZone(zone);
                }}
              />
            ))}
            {overflowZones.length > 0 && !zoneExpanded && (
              <button
                type="button"
                onClick={() => {
                  setZoneExpanded(true);
                }}
                className="rounded-full border px-3 py-1.5 text-xs font-semibold text-white/50"
                style={{ borderColor: "hsl(var(--border))" }}
              >
                {t("gifts.game.otherRegion")}
              </button>
            )}
            {zoneExpanded &&
              overflowZones.map((zone) => (
                <ZonePill
                  key={zone}
                  zone={zone}
                  active={zone === selectedZone}
                  available={selectedPackage?.prices.some((p) => p.zone === zone) ?? false}
                  onSelect={() => {
                    selectZone(zone);
                  }}
                />
              ))}
          </div>
        </div>

        {/* Price */}
        <div className="border-t pt-4" style={{ borderColor: "hsl(var(--border) / 0.7)" }}>
          {price ? (
            <p className="text-2xl font-bold tabular-nums text-white">{priceLabel(price)}</p>
          ) : (
            <p className="text-sm text-white/50">{t("gifts.game.noPriceInRegion")}</p>
          )}
        </div>

        {/* Invite link */}
        <div className="space-y-2">
          <label className="text-[11px] font-semibold uppercase tracking-wide text-white/50">
            {t("gifts.game.inviteLabel")}
          </label>
          <input
            type="text"
            value={inviteUrl}
            onChange={(e) => {
              setInviteUrl(e.target.value);
            }}
            placeholder={t("gifts.game.invitePlaceholder")}
            className="h-11 w-full rounded-xl border bg-transparent px-3 text-sm text-white outline-none"
            style={{ borderColor: "hsl(var(--border))" }}
          />
          {inviteTouched && canonicalInvite === null && (
            <p className="text-[13px] text-red-400">{t("gifts.game.inviteError")}</p>
          )}
          <button
            type="button"
            onClick={() => {
              setGuideOpen(true);
            }}
            className="text-primary text-[13px] font-semibold"
          >
            {t("gifts.game.inviteGuideCta")}
          </button>
        </div>

        <button
          type="button"
          disabled={!canBuy}
          onClick={handleBuy}
          className="bg-primary w-full rounded-2xl py-3.5 text-base font-bold text-black disabled:cursor-not-allowed disabled:opacity-50"
        >
          {t("gifts.game.buy")}
        </button>

        <div className="space-y-1 text-[12px] leading-relaxed text-white/40">
          <p>{t("gifts.game.timeline")}</p>
          <p>{t("gifts.game.accept")}</p>
        </div>
      </div>
    </motion.div>
  );
}
