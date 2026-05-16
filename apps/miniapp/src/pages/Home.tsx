import { useState, useMemo, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Search, X, TrendingUp, ArrowLeft, ShieldCheck, Zap, Headphones, RotateCcw } from "lucide-react";
import { GAMES, HISTORY, CATEGORY_LABELS, type Category, type Game } from "@/lib/constants";
import { Link } from "wouter";

const CATEGORIES: { key: Category | "all"; label: string }[] = [
  { key: "all", label: "Все" },
  { key: "games", label: "Игры" },
  { key: "services", label: "Сервисы" },
  { key: "cards", label: "Карты" },
];

const FEATURED_IDS = ["pubg", "telegram", "delta-force", "steam", "valorant"];

const PROMO_BADGES: Record<string, { label: string; color: string }> = {
  pubg: { label: "ТОП", color: "hsl(var(--primary))" },
  telegram: { label: "АКЦИЯ", color: "#ff6b35" },
  "delta-force": { label: "НОВИНКА", color: "#a855f7" },
};

// ─── Trust bar ────────────────────────────────────────────────────────────────
function TrustBar() {
  const items = [
    { icon: ShieldCheck, label: "Защита платежей" },
    { icon: Zap, label: "До 5 минут" },
    { icon: Headphones, label: "Поддержка 24/7" },
  ];
  return (
    <div className="flex items-center justify-between px-4 py-2.5 mx-4 rounded-2xl"
      style={{ background: "hsl(228 32% 17%)", border: "1px solid hsl(var(--border))" }}
    >
      {items.map(({ icon: Icon, label }, i) => (
        <div key={i} className="flex items-center gap-1.5">
          <Icon size={13} className="text-primary flex-shrink-0" />
          <span className="text-[11px] text-white/50 font-medium whitespace-nowrap">{label}</span>
        </div>
      ))}
    </div>
  );
}

// ─── Recent games strip ────────────────────────────────────────────────────────
function RecentStrip() {
  const recentGameIds = [...new Map(HISTORY.map((h) => [h.gameId, h])).values()].slice(0, 4);
  const recentGames = recentGameIds
    .map((h) => ({ ...h, game: GAMES.find((g) => g.id === h.gameId)! }))
    .filter((r) => r.game);

  if (recentGames.length === 0) return null;

  return (
    <div className="px-4">
      <div className="flex items-center gap-2 mb-2.5">
        <RotateCcw size={13} className="text-white/40" />
        <span className="text-xs font-semibold text-white/50 uppercase tracking-wide">Недавние</span>
      </div>
      <div className="flex gap-2 overflow-x-auto no-scrollbar">
        {recentGames.map(({ game, amount }, i) => (
          <Link key={game.id} href={`/topup/${game.id}`}>
            <motion.div
              whileTap={{ scale: 0.94 }}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              className="flex items-center gap-2.5 flex-shrink-0 px-3 py-2 rounded-2xl cursor-pointer"
              style={{ background: "hsl(228 32% 17%)", border: "1px solid hsl(var(--border))" }}
            >
              {/* mini icon */}
              <div className="w-8 h-8 rounded-[22%] overflow-hidden flex-shrink-0">
                {game.appIcon ? (
                  <img src={game.appIcon} className="w-full h-full object-cover" alt={game.name} />
                ) : game.bgUrl ? (
                  <img src={game.bgUrl} className="w-full h-full object-cover" alt={game.name} />
                ) : (
                  <div className={`w-full h-full bg-gradient-to-br ${game.gradient || "from-card to-background"} flex items-center justify-center`}>
                    {game.icon && <game.icon style={{ width: 16, height: 16, color: game.iconColor || "#fff" }} />}
                  </div>
                )}
              </div>
              <div>
                <p className="text-white text-xs font-semibold leading-tight line-clamp-1 max-w-[80px]">{game.name}</p>
                <p className="text-white/40 text-[10px] mt-0.5">₽{amount.toLocaleString("ru")}</p>
              </div>
            </motion.div>
          </Link>
        ))}
      </div>
    </div>
  );
}

// ─── Promo strip ──────────────────────────────────────────────────────────────
function PromoStrip() {
  const featured = GAMES.filter((g) => FEATURED_IDS.includes(g.id));

  return (
    <div>
      <div className="flex items-center justify-between px-4 mb-3">
        <div className="flex items-center gap-2">
          <TrendingUp size={14} className="text-primary" />
          <span className="text-sm font-semibold text-white">Популярное</span>
        </div>
        <span className="text-xs text-white/30">{featured.length} сервисов</span>
      </div>
      <div className="flex gap-3 overflow-x-auto no-scrollbar px-4 pb-1">
        {featured.map((game, i) => {
          const badge = PROMO_BADGES[game.id];
          return (
            <Link key={game.id} href={`/topup/${game.id}`}>
              <motion.div
                whileTap={{ scale: 0.94 }}
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.06 }}
                className="relative flex-shrink-0 w-[148px] h-[108px] rounded-2xl overflow-hidden cursor-pointer"
              >
                {game.appIcon || game.bgUrl ? (
                  <img
                    src={game.appIcon || game.bgUrl}
                    className="absolute inset-0 w-full h-full object-cover"
                    alt={game.name}
                  />
                ) : (
                  <div className={`absolute inset-0 bg-gradient-to-br ${game.gradient || "from-card to-background"}`} />
                )}
                <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/10 to-transparent" />

                {badge && (
                  <div
                    className="absolute top-2 left-2 px-1.5 py-0.5 rounded-md text-[9px] font-bold tracking-wider"
                    style={{ background: badge.color, color: badge.color === "hsl(var(--primary))" ? "#000" : "#fff" }}
                  >
                    {badge.label}
                  </div>
                )}

                <div className="absolute bottom-0 left-0 right-0 p-3">
                  <p className="text-white font-semibold text-xs leading-tight line-clamp-1">{game.name}</p>
                  <p className="text-white/50 text-[10px] mt-0.5">{game.publisher}</p>
                </div>
              </motion.div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

// ─── Game card (icon grid) ────────────────────────────────────────────────────
function GameCard({ game, index }: { game: Game; index: number }) {
  return (
    <Link href={`/topup/${game.id}`}>
      <motion.div
        whileTap={{ scale: 0.91 }}
        initial={{ opacity: 0, scale: 0.82 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: index * 0.025, type: "spring", stiffness: 300, damping: 24 }}
        className="flex flex-col items-center gap-1.5"
        data-testid={`card-game-${game.id}`}
      >
        <div className="w-full aspect-square rounded-[22%] overflow-hidden shadow-md">
          {game.appIcon ? (
            <img src={game.appIcon} className="w-full h-full object-cover" alt={game.name} />
          ) : game.bgUrl ? (
            <img src={game.bgUrl} className="w-full h-full object-cover" alt={game.name} />
          ) : (
            <div className={`w-full h-full bg-gradient-to-br ${game.gradient || "from-card to-background"} flex items-center justify-center`}>
              {game.icon && <game.icon style={{ width: 34, height: 34, color: game.iconColor || "#fff" }} />}
            </div>
          )}
        </div>
        <p className="text-white/80 text-[11px] font-medium text-center leading-tight line-clamp-1 w-full px-0.5">
          {game.name}
        </p>
      </motion.div>
    </Link>
  );
}

// ─── Search result row ────────────────────────────────────────────────────────
function SearchResultCard({ game, index }: { game: Game; index: number }) {
  return (
    <Link href={`/topup/${game.id}`}>
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: index * 0.04 }}
        whileTap={{ scale: 0.97 }}
        className="flex items-center gap-3 p-3 rounded-2xl bg-card border border-border"
      >
        <div className="w-11 h-11 rounded-[22%] overflow-hidden flex-shrink-0">
          {game.appIcon ? (
            <img src={game.appIcon} className="w-full h-full object-cover" alt={game.name} />
          ) : game.bgUrl ? (
            <img src={game.bgUrl} className="w-full h-full object-cover" alt={game.name} />
          ) : (
            <div className={`w-full h-full bg-gradient-to-br ${game.gradient || "from-card to-background"} flex items-center justify-center`}>
              {game.icon && <game.icon style={{ width: 20, height: 20, color: game.iconColor || "#fff" }} />}
            </div>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-white text-sm font-semibold line-clamp-1">{game.name}</p>
          <p className="text-white/40 text-xs mt-0.5">{game.publisher}</p>
        </div>
        <span className="text-[10px] font-medium px-2 py-0.5 rounded-full border border-white/10 text-white/40 flex-shrink-0">
          {CATEGORY_LABELS[game.category]}
        </span>
      </motion.div>
    </Link>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────
export default function Home() {
  const [search, setSearch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [activeCategory, setActiveCategory] = useState<Category | "all">("all");
  const inputRef = useRef<HTMLInputElement>(null);

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
    return GAMES.filter(
      (g) => g.name.toLowerCase().includes(q) || g.publisher.toLowerCase().includes(q)
    );
  }, [search]);

  const filtered =
    activeCategory === "all" ? GAMES : GAMES.filter((g) => g.category === activeCategory);

  const displayGames = searchOpen && search.trim() ? searchResults : filtered;

  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
      className="space-y-4 pb-2"
    >
      {/* ── Header ── */}
      <div className="px-4 pt-4">
        <h1 className="text-xl font-bold tracking-tight text-white leading-tight">
          Пополнение игр
        </h1>
        <p className="text-white/35 text-xs mt-0.5">{GAMES.length} сервисов · Оплата картой и СБП</p>
      </div>

      <AnimatePresence>
        {!searchOpen && (
          <motion.div
            key="main-content"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.18 }}
          >
            <PromoStrip />
          </motion.div>
        )}
      </AnimatePresence>

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
                className="flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center"
                style={{ background: "hsl(var(--card))", border: "1.5px solid hsl(var(--border))" }}
              >
                <ArrowLeft size={15} className="text-white/60" />
              </button>
              <div className="relative flex-1">
                <Search
                  size={15}
                  className="absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none"
                  style={{ color: "hsl(var(--primary) / 0.7)" }}
                />
                <input
                  ref={inputRef}
                  type="text"
                  placeholder="Найти игру..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="w-full rounded-xl pl-9 pr-9 py-2.5 text-sm text-white placeholder:text-white/30 outline-none transition-all"
                  style={{
                    background: "hsl(228 32% 18%)",
                    border: "1.5px solid hsl(var(--primary) / 0.45)",
                    boxShadow: "0 0 0 3px hsl(var(--primary) / 0.08)",
                  }}
                />
                {search && (
                  <button
                    onClick={() => setSearch("")}
                    className="absolute right-3 top-1/2 -translate-y-1/2 p-0.5 rounded-full bg-white/10"
                  >
                    <X size={12} className="text-white/60" />
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
              className="flex gap-2 overflow-x-auto no-scrollbar"
            >
              {/* Search button on the LEFT */}
              <button
                onClick={openSearch}
                className="flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center transition-all"
                style={{ background: "hsl(var(--card))", border: "1.5px solid hsl(var(--border))" }}
                data-testid="open-search"
              >
                <Search size={15} className="text-white/50" />
              </button>
              {CATEGORIES.map((cat) => (
                <button
                  key={cat.key}
                  onClick={() => setActiveCategory(cat.key as Category | "all")}
                  className="whitespace-nowrap rounded-xl px-3.5 py-2 text-xs font-semibold transition-all duration-200 flex-shrink-0"
                  style={{
                    background: activeCategory === cat.key ? "hsl(var(--primary))" : "hsl(var(--card))",
                    color: activeCategory === cat.key ? "#000" : "rgba(255,255,255,0.5)",
                    border: activeCategory === cat.key
                      ? "1.5px solid hsl(var(--primary))"
                      : "1.5px solid hsl(var(--border))",
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
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-semibold text-white">
                {searchOpen && search.trim() ? "Результаты" : "Все сервисы"}
              </span>
              <span className="text-xs text-white/30">{displayGames.length} позиций</span>
            </div>

            {displayGames.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-14 gap-2">
                <Search size={28} className="text-white/15" />
                <p className="text-white/30 text-sm">Ничего не найдено</p>
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
