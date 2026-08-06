import { motion, AnimatePresence } from "framer-motion";
import { Search, X, ArrowLeft, RotateCcw, Settings } from "lucide-react";
import { useState, useMemo, useRef } from "react";
import { Link } from "wouter";

import type { Game } from "@/lib/constants-types";

import { HomePromoCards } from "@/components/HomePromoCards";
import { listRecent } from "@/lib/recent-checkout";
import { SafeImage } from "@/components/ui/safe-image";
import { useCategoriesList, useGames } from "@/lib/catalog";
import { CATEGORY_LABELS } from "@/lib/constants";
import { useT } from "@/lib/i18n";
import { useDocumentTitle } from "@/lib/use-document-title";

const ALL_KEY = "__all__";

// ─── Game card (icon grid) ────────────────────────────────────────────────────
function GameCardThumb({ game }: { game: Game }) {
  const fallback = (
    <div
      className={`h-full w-full bg-gradient-to-br ${game.gradient || "from-card to-background"} flex items-center justify-center`}
    >
      {game.icon && (
        <game.icon style={{ width: 34, height: 34, color: game.iconColor || "#fff" }} />
      )}
    </div>
  );
  const src = game.appIcon || game.bgUrl;
  if (!src) return fallback;
  return <SafeImage src={src} className="h-full w-full object-cover" fallback={fallback} />;
}

function GameCard({ game, index }: { game: Game; index: number }) {
  const { t } = useT();
  const inner = (
    <motion.div
      whileTap={game.maintenance ? undefined : { scale: 0.91 }}
      initial={{ opacity: 0, scale: 0.82 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay: index * 0.025, type: "spring", stiffness: 300, damping: 24 }}
      className="flex flex-col items-center gap-1.5"
      data-testid={`card-game-${game.id}`}
    >
      <div className="relative aspect-square w-full overflow-hidden rounded-2xl shadow-md">
        <div className={game.maintenance ? "h-full w-full opacity-35 grayscale" : "h-full w-full"}>
          <GameCardThumb game={game} />
        </div>
        {game.maintenance && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-black/45 px-1 text-center">
            <Settings size={20} className="animate-spin text-white/85 [animation-duration:4s]" />
            <span className="text-[8.5px] font-semibold uppercase leading-tight tracking-wide text-white/85">
              {t("home.maintenanceL1")}
              <br />
              {t("home.maintenanceL2")}
            </span>
          </div>
        )}
      </div>
      <p
        className={`line-clamp-1 w-full px-0.5 text-center text-[11px] font-medium leading-tight ${game.maintenance ? "text-white/40" : "text-white/80"}`}
      >
        {game.name}
      </p>
    </motion.div>
  );

  if (game.maintenance) {
    return (
      <div aria-disabled="true" className="cursor-not-allowed">
        {inner}
      </div>
    );
  }
  return <Link href={`/topup/${game.id}`}>{inner}</Link>;
}

// ─── Search result row ────────────────────────────────────────────────────────
function SearchResultThumb({ game }: { game: Game }) {
  const fallback = (
    <div
      className={`h-full w-full bg-gradient-to-br ${game.gradient || "from-card to-background"} flex items-center justify-center`}
    >
      {game.icon && (
        <game.icon style={{ width: 20, height: 20, color: game.iconColor || "#fff" }} />
      )}
    </div>
  );
  const src = game.appIcon || game.bgUrl;
  if (!src) return fallback;
  return <SafeImage src={src} className="h-full w-full object-cover" fallback={fallback} />;
}

function SearchResultCard({ game, index }: { game: Game; index: number }) {
  const { t } = useT();
  const inner = (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04 }}
      whileTap={game.maintenance ? undefined : { scale: 0.97 }}
      className="bg-card border-border flex items-center gap-3 rounded-2xl border p-3"
    >
      <div className="relative h-11 w-11 flex-shrink-0 overflow-hidden rounded-2xl">
        <div className={game.maintenance ? "h-full w-full opacity-35 grayscale" : "h-full w-full"}>
          <SearchResultThumb game={game} />
        </div>
        {game.maintenance && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/45">
            <Settings size={16} className="animate-spin text-white/85 [animation-duration:4s]" />
          </div>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p
          className={`line-clamp-1 text-sm font-semibold ${game.maintenance ? "text-white/50" : "text-white"}`}
        >
          {game.name}
        </p>
        <p className="text-body-faint mt-0.5 text-xs">
          <span className="line-clamp-1">
            {game.maintenance ? t("home.maintenance") : game.publisher}
          </span>
        </p>
      </div>
      <span className="text-body-faint flex-shrink-0 rounded-full border border-white/10 px-2 py-0.5 text-[10px] font-medium">
        {t(CATEGORY_LABELS[game.category])}
      </span>
    </motion.div>
  );

  if (game.maintenance) {
    return (
      <div aria-disabled="true" className="cursor-not-allowed">
        {inner}
      </div>
    );
  }
  return <Link href={`/topup/${game.id}`}>{inner}</Link>;
}

// ─── Main page ────────────────────────────────────────────────────────────────
export default function Home() {
  const { t, tn } = useT();
  useDocumentTitle(t("home.docTitle"));
  const [search, setSearch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [activeCategory, setActiveCategory] = useState<string>(ALL_KEY);
  const inputRef = useRef<HTMLInputElement>(null);

  const gamesQuery = useGames();
  const games = gamesQuery.data ?? [];

  // Only brands that still exist in the catalogue, carrying their current name
  // rather than whatever was stored months ago.
  const recent = useMemo(
    () =>
      listRecent(3)
        .map((entry) => {
          const game = games.find((g) => g.id === entry.brand_slug);
          return game ? { ...entry, name: game.name } : null;
        })
        .filter((x): x is (typeof x & { name: string }) & object => x !== null),
    [games],
  );
  const categoriesQuery = useCategoriesList();
  const apiCategories = categoriesQuery.data ?? [];
  // Only show category chips that actually have at least one brand attached —
  // an empty filter is just visual noise.
  const visibleCategorySlugs = new Set(
    games.map((g) => g.category_slug).filter(Boolean) as string[],
  );
  const categoryChips: { key: string; label: string }[] = [
    { key: ALL_KEY, label: t("home.all") },
    ...apiCategories
      .filter((c) => visibleCategorySlugs.has(c.slug))
      .map((c) => ({ key: c.slug, label: c.name })),
  ];

  const openSearch = () => {
    setSearchOpen(true);
    setSearch("");
    setTimeout(() => inputRef.current?.focus(), 120);
  };

  const closeSearch = () => {
    setSearchOpen(false);
    setSearch("");
  };

  const searchResults = useMemo(() => {
    const q = search.toLowerCase().trim();
    if (!q) return [];
    return games.filter(
      // Name only: `publisher` used to hold the brand's SEO paragraph, so a
      // query like "оплата" matched the entire catalogue at once.
      (g) => g.name.toLowerCase().includes(q),
    );
  }, [search, games]);

  const filtered =
    activeCategory === ALL_KEY ? games : games.filter((g) => g.category_slug === activeCategory);

  const displayGames = searchOpen && search.trim() ? searchResults : filtered;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.22 }}
      className="space-y-4 pb-2"
    >
      {/* ── Header ── */}
      <div className="px-4 pt-4">
        <h1 className="text-xl font-bold leading-tight tracking-tight text-white">
          {t("home.title")}
        </h1>
        <p className="text-body-muted mt-0.5 text-xs">
          {tn("home.servicesCount", games.length)} · {t("home.payNote")}
        </p>
      </div>

      <AnimatePresence>
        {!searchOpen && (
          <motion.div
            key="main-content"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.18 }}
            className="space-y-3.5"
          >
            <HomePromoCards />
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Buy again ── */}
      {/* Topping up is a repeat purchase on a short cycle, but a returning
          buyer walked exactly the same path as a first-timer: find the icon,
          open it, pick the pack, retype the id. Everything needed to skip that
          was already in localStorage after the first checkout — it just had no
          reader. */}
      {recent.length > 0 && !searchOpen && (
        <div className="px-4 pt-1">
          <p className="mb-2 text-sm font-semibold text-white">{t("home.recentTitle")}</p>
          <div className="flex gap-2 overflow-x-auto pb-1">
            {recent.map((r) => (
              <Link
                key={r.brand_slug}
                href={`/topup/${r.brand_slug}?sku=${encodeURIComponent(r.sku_id ?? "")}`}
                className="border-border bg-card flex shrink-0 items-center gap-2 rounded-2xl border px-3 py-2.5 active:opacity-70"
              >
                <span className="min-w-0">
                  <span className="block truncate text-[13px] font-semibold text-white">
                    {r.name}
                  </span>
                  <span className="text-body-faint block truncate text-[11px]">{r.sku_label}</span>
                </span>
                <RotateCcw size={14} className="text-primary shrink-0" aria-hidden />
              </Link>
            ))}
          </div>
        </div>
      )}

      {/* ── Category row + search ── */}
      <div className="px-4">
        <AnimatePresence mode="wait">
          {searchOpen ? (
            <motion.div
              key="searchbar"
              initial={{ opacity: 0, scaleX: 0.92 }}
              animate={{ opacity: 1, scaleX: 1 }}
              exit={{ opacity: 0, scaleX: 0.92 }}
              transition={{ type: "spring", stiffness: 400, damping: 30 }}
              className="flex items-center gap-2"
            >
              <button
                onClick={closeSearch}
                className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl"
                style={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))" }}
              >
                <ArrowLeft size={15} className="text-white/60" />
              </button>
              <div className="relative flex-1">
                <Search
                  size={15}
                  className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2"
                  style={{ color: "hsl(var(--primary) / 0.7)" }}
                />
                <input
                  ref={inputRef}
                  type="search"
                  role="searchbox"
                  aria-label={t("home.searchAria")}
                  placeholder={t("home.searchPlaceholder")}
                  value={search}
                  onChange={(e) => {
                    setSearch(e.target.value);
                  }}
                  className="placeholder:text-body-faint w-full rounded-xl py-2.5 pl-9 pr-9 text-sm text-white outline-none transition-all"
                  style={{
                    background: "hsl(var(--surface-2))",
                    border: "1.5px solid hsl(var(--primary) / 0.45)",
                    boxShadow: "0 0 0 3px hsl(var(--primary) / 0.08)",
                  }}
                />
                {search && (
                  <button
                    onClick={() => {
                      setSearch("");
                    }}
                    aria-label={t("home.clearSearch")}
                    className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full bg-white/10 p-0.5"
                  >
                    <X size={12} className="text-white/60" aria-hidden="true" />
                  </button>
                )}
              </div>
            </motion.div>
          ) : (
            <motion.div
              key="pills"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="no-scrollbar flex gap-2 overflow-x-auto"
            >
              {/* Search trigger on the LEFT — icon + label, not a bare 36px
                  icon: a bigger tap target and it reads as "search" without
                  decoding the glyph. */}
              <button
                onClick={openSearch}
                className="flex h-9 flex-shrink-0 items-center gap-1.5 rounded-xl px-3 transition-all"
                style={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))" }}
                data-testid="open-search"
              >
                <Search size={15} className="text-body-muted" aria-hidden="true" />
                <span className="text-body-muted text-xs font-semibold">
                  {t("home.searchButton")}
                </span>
              </button>
              {categoryChips.map((cat) => (
                <button
                  key={cat.key}
                  onClick={() => {
                    setActiveCategory(cat.key);
                  }}
                  className="flex-shrink-0 whitespace-nowrap rounded-xl px-3.5 py-2 text-xs font-semibold transition-all duration-200"
                  style={{
                    background:
                      activeCategory === cat.key ? "hsl(var(--primary))" : "hsl(var(--card))",
                    color: activeCategory === cat.key ? "#000" : "rgba(255,255,255,0.5)",
                    border:
                      activeCategory === cat.key
                        ? "1px solid hsl(var(--primary))"
                        : "1px solid hsl(var(--border))",
                  }}
                  data-testid={`filter-${cat.key}`}
                >
                  {cat.label}
                </button>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* ── Icon grid (category filter OR search filter) ── */}
      <div className="px-4">
        <AnimatePresence mode="wait">
          <motion.div
            key={searchOpen ? `search-${search}` : `grid-${activeCategory}`}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.16 }}
          >
            <div className="mb-3 flex items-center justify-between">
              <span className="text-sm font-semibold text-white">
                {searchOpen && search.trim() ? t("home.results") : t("home.allServices")}
              </span>
              <div className="flex items-center gap-2">
                <span className="text-body-faint text-xs">
                  {tn("home.positionsCount", displayGames.length)}
                </span>
                <button
                  type="button"
                  onClick={() => gamesQuery.refetch()}
                  disabled={gamesQuery.isFetching}
                  className="flex h-7 w-7 items-center justify-center rounded-full transition-colors disabled:opacity-40"
                  style={{
                    background: "hsl(var(--surface-2))",
                    border: "1px solid hsl(var(--border))",
                  }}
                  aria-label={t("home.refresh")}
                >
                  <RotateCcw
                    size={11}
                    className={`text-white/60 ${gamesQuery.isFetching ? "animate-spin" : ""}`}
                  />
                </button>
              </div>
            </div>

            {gamesQuery.isLoading ? (
              <div className="grid grid-cols-4 gap-x-2 gap-y-4">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div key={i} className="flex flex-col items-center gap-1.5">
                    <div
                      className="aspect-square w-full animate-pulse rounded-2xl"
                      style={{ background: "hsl(var(--surface-2))" }}
                    />
                    <div
                      className="h-2 w-3/4 animate-pulse rounded"
                      style={{ background: "hsl(var(--surface-2))" }}
                    />
                  </div>
                ))}
              </div>
            ) : displayGames.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-2 py-14">
                <Search size={28} className="text-white/15" />
                <p className="text-body-faint text-sm">{t("home.nothingFound")}</p>
                {searchOpen && search.trim() !== "" && (
                  <button
                    type="button"
                    onClick={closeSearch}
                    className="text-primary mt-1 text-sm font-semibold"
                    data-testid="reset-search"
                  >
                    {t("home.resetSearch")}
                  </button>
                )}
              </div>
            ) : (
              <div className="grid grid-cols-4 gap-x-2 gap-y-4">
                {displayGames.map((game, index) => (
                  <GameCard key={game.id} game={game} index={index} />
                ))}
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
