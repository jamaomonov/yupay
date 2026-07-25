import { useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import SkinCard, { Skin } from "@/components/SkinCard";
import SkinMarketFilters, { FilterState } from "@/components/SkinMarketFilters";

// Mock data - in real app, this would come from an API
const MOCK_SKINS: Skin[] = [
  {
    id: "1",
    name: "Dragon Lore",
    series: "Souvenir AWP",
    weapon: "AWP Dragon Lore",
    price: 13191.72,
    floatValue: 0.0694030,
    condition: "FN",
    borderColor: "from-pink-500",
    stickers: 3,
  },
  {
    id: "2",
    name: "Dragon Lore",
    series: "Souvenir AWP",
    weapon: "AWP Dragon Lore",
    price: 70000.0,
    floatValue: 0.0965510,
    condition: "MW",
    borderColor: "from-yellow-500",
    stickers: 4,
  },
  {
    id: "3",
    name: "Nitro",
    series: "Souvenir M4A1-S",
    weapon: "M4A1-S Nitro",
    price: 44.63,
    floatValue: 0.0673873,
    condition: "FN",
    borderColor: "from-purple-500",
    stickers: 3,
    discount: 13,
  },
  {
    id: "4",
    name: "Dragon Lore",
    series: "Souvenir AWP",
    weapon: "AWP Dragon Lore",
    price: 29999.0,
    floatValue: 0.6163723,
    condition: "BS",
    borderColor: "from-lime-500",
    stickers: 3,
  },
  {
    id: "5",
    name: "Asilimov",
    series: "AWP",
    weapon: "AWP Asiimov",
    price: 9229.68,
    floatValue: 0.1234567,
    condition: "MW",
    borderColor: "from-blue-500",
    stickers: 2,
    discount: 8,
  },
  {
    id: "6",
    name: "Fade",
    series: "Glock-18",
    weapon: "Glock-18 Fade",
    price: 2250.75,
    floatValue: 0.0123456,
    condition: "FN",
    borderColor: "from-rose-500",
    stickers: 4,
  },
  {
    id: "7",
    name: "Phantom Disruptor",
    series: "Crescent",
    weapon: "Phantom Disruptor",
    price: 1850.5,
    floatValue: 0.0987654,
    condition: "MW",
    borderColor: "from-green-500",
    stickers: 3,
    discount: 5,
  },
  {
    id: "8",
    name: "Howl",
    series: "Contraband",
    weapon: "M4A4 Howl",
    price: 8862.63,
    floatValue: 0.0865510,
    condition: "FN",
    borderColor: "from-indigo-500",
    stickers: 4,
  },
  {
    id: "9",
    name: "Vulcan",
    series: "Recoil",
    weapon: "AK-47 Vulcan",
    price: 3299.99,
    floatValue: 0.1456789,
    condition: "FT",
    borderColor: "from-pink-500",
    stickers: 2,
    discount: 10,
  },
];

export default function CS2SkinMarket() {
  const [filters, setFilters] = useState<FilterState>({
    search: "",
    sortBy: "newest",
    conditions: [],
  });
  const [cartItems, setCartItems] = useState<string[]>([]);

  const filteredAndSortedSkins = useMemo(() => {
    let result = [...MOCK_SKINS];

    // Filter by search
    if (filters.search) {
      const searchLower = filters.search.toLowerCase();
      result = result.filter(
        (skin) =>
          skin.name.toLowerCase().includes(searchLower) ||
          skin.weapon.toLowerCase().includes(searchLower) ||
          skin.series.toLowerCase().includes(searchLower)
      );
    }

    // Filter by conditions
    if (filters.conditions.length > 0) {
      result = result.filter((skin) =>
        filters.conditions.includes(skin.condition)
      );
    }

    // Sort
    switch (filters.sortBy) {
      case "price-asc":
        result.sort((a, b) => a.price - b.price);
        break;
      case "price-desc":
        result.sort((a, b) => b.price - a.price);
        break;
      case "float-asc":
        result.sort((a, b) => a.floatValue - b.floatValue);
        break;
      case "float-desc":
        result.sort((a, b) => b.floatValue - a.floatValue);
        break;
      case "newest":
      default:
        // Keep original order
        break;
    }

    return result;
  }, [filters]);

  const handleBuy = (skinId: string) => {
    // Demo stub: real checkout/payment wiring lands with the CS2 market API.
    void MOCK_SKINS.find((s) => s.id === skinId);
  };

  const handleAddToCart = (skinId: string) => {
    setCartItems((prev) => (prev.includes(skinId) ? prev : [...prev, skinId]));
  };

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="sticky top-0 z-30 bg-background/95 backdrop-blur-sm border-b border-white/10 px-4 py-4">
          <div className="flex items-center justify-between">
            <h1 className="text-2xl font-bold text-foreground">
              CS2 Skins Market
            </h1>
            {cartItems.length > 0 && (
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                className="inline-flex items-center gap-2 bg-primary/20 text-primary px-3 py-1.5 rounded-full text-sm font-semibold"
              >
                <span>🛒</span>
                <span>{cartItems.length}</span>
              </motion.div>
            )}
          </div>
        </div>

        {/* Filters */}
        <SkinMarketFilters
          filters={filters}
          onFiltersChange={setFilters}
          resultCount={filteredAndSortedSkins.length}
        />

        {/* Content */}
        <div className="px-4 py-6">
          {filteredAndSortedSkins.length === 0 ? (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex flex-col items-center justify-center py-16 text-center"
            >
              <div className="text-6xl mb-4">🔍</div>
              <h2 className="text-xl font-bold text-foreground mb-2">
                No skins found
              </h2>
              <p className="text-white/60">
                Try adjusting your filters or search terms
              </p>
              <motion.button
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                onClick={() =>
                  setFilters({
                    search: "",
                    sortBy: "newest",
                    conditions: [],
                  })
                }
                className="mt-6 px-6 py-2 bg-primary text-background font-semibold rounded-md hover:bg-primary/90 transition-colors"
              >
                Clear all filters
              </motion.button>
            </motion.div>
          ) : (
            <motion.div
              layout
              className="grid grid-cols-2 gap-4 auto-rows-max"
            >
              <AnimatePresence mode="popLayout">
                {filteredAndSortedSkins.map((skin) => (
                  <motion.div
                    key={skin.id}
                    layout
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                  >
                    <SkinCard
                      skin={skin}
                      onBuy={handleBuy}
                      onAddToCart={handleAddToCart}
                    />
                  </motion.div>
                ))}
              </AnimatePresence>
            </motion.div>
          )}
        </div>

        {/* Footer Spacing */}
        <div className="h-24" />
      </div>
    </div>
  );
}
