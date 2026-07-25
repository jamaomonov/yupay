import { motion } from "framer-motion";
import { ShoppingCart } from "lucide-react";

export interface Skin {
  id: string;
  name: string;
  series: string;
  weapon: string;
  price: number;
  floatValue: number;
  condition: "FN" | "MW" | "FT" | "WW" | "BS";
  discount?: number;
  borderColor: string;
  stickers: number;
}

interface SkinCardProps {
  skin: Skin;
  onBuy: (skinId: string) => void;
  onAddToCart: (skinId: string) => void;
}

const conditionLabels = {
  FN: "Factory New",
  MW: "Minimal Wear",
  FT: "Field-Tested",
  WW: "Well-Worn",
  BS: "Battle-Scarred",
};

export default function SkinCard({
  skin,
  onBuy,
  onAddToCart,
}: SkinCardProps) {
  const borderColorMap: Record<string, string> = {
    "from-pink-500": "border-pink-500",
    "from-yellow-500": "border-yellow-500",
    "from-purple-500": "border-purple-500",
    "from-lime-500": "border-lime-500",
    "from-blue-500": "border-blue-500",
    "from-rose-500": "border-rose-500",
    "from-green-500": "border-green-500",
    "from-indigo-500": "border-indigo-500",
  };

  const borderClass = borderColorMap[skin.borderColor] || "border-lime-500";

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 20 }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
      whileHover={{ scale: 1.02 }}
      className="relative flex flex-col rounded-lg border-2 overflow-hidden bg-surface transition-all duration-300"
      style={{
        borderColor: getBorderColor(skin.borderColor),
        boxShadow: `0 0 20px ${getBorderColor(skin.borderColor)}40`,
      }}
    >
      {/* Price Badge */}
      <div className="absolute top-3 left-3 z-10 flex items-center gap-1.5 bg-surface-variant/90 backdrop-blur-sm px-3 py-1.5 rounded-md border border-surface-bright/30">
        <svg
          className="w-4 h-4"
          viewBox="0 0 24 24"
          fill="currentColor"
          style={{ color: "var(--primary)" }}
        >
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm3.5-9c.83 0 1.5-.67 1.5-1.5S16.33 8 15.5 8 14 8.67 14 9.5s.67 1.5 1.5 1.5zm-7 0c.83 0 1.5-.67 1.5-1.5S9.33 8 8.5 8 7 8.67 7 9.5 7.67 11 8.5 11zm3.5 6.5c2.33 0 4.31-1.46 5.11-3.5H6.89c.8 2.04 2.78 3.5 5.11 3.5z" />
        </svg>
        <span className="text-sm font-semibold text-primary">
          ${skin.price.toLocaleString("en-US", { maximumFractionDigits: 2 })}
        </span>
      </div>

      {/* Discount Badge */}
      {skin.discount && (
        <div className="absolute top-3 right-3 z-10 bg-red-500/90 backdrop-blur-sm px-2 py-1 rounded-md text-xs font-bold text-white">
          -{skin.discount}%
        </div>
      )}

      {/* Weapon Image Container */}
      <div className="relative w-full aspect-square bg-surface-variant/50 flex items-center justify-center overflow-hidden border-b border-surface-bright/10">
        <div
          className="absolute inset-0 opacity-10"
          style={{
            backgroundImage:
              "repeating-linear-gradient(45deg, transparent, transparent 10px, rgba(180,236,81,0.1) 10px, rgba(180,236,81,0.1) 20px)",
          }}
        />
        <div
          className="absolute inset-0 flex items-center justify-center text-6xl font-bold text-surface-bright/5"
        >
          🔫
        </div>

        {/* Hexagon Border */}
        <div
          className="absolute w-4/5 h-4/5 rounded-lg pointer-events-none"
          style={{
            border: `3px solid ${getBorderColor(skin.borderColor)}`,
            clipPath:
              "polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)",
          }}
        />
      </div>

      {/* Content */}
      <div className="flex-1 p-4 flex flex-col">
        {/* Stickers */}
        <div className="flex gap-2 mb-3">
          {Array.from({ length: skin.stickers }).map((_, i) => (
            <div
              key={i}
              className="w-6 h-6 rounded-full bg-gradient-to-br from-amber-400 to-amber-600 flex items-center justify-center text-xs font-bold text-amber-950"
            >
              ★
            </div>
          ))}
        </div>

        {/* Series */}
        <div className="text-xs font-semibold text-amber-400 uppercase tracking-wide mb-1">
          {skin.series}
        </div>

        {/* Weapon Name */}
        <h3 className="text-base font-bold text-foreground mb-2 truncate">
          {skin.name}
        </h3>

        {/* Condition and Float */}
        <div className="flex justify-between items-center text-xs mb-3">
          <span className="text-surface-bright">
            <strong>{skin.condition}</strong>
          </span>
          <span className="text-surface-bright/70">
            {skin.floatValue.toFixed(7)}
          </span>
        </div>

        {/* Price */}
        <div className="mb-3 pb-3 border-b border-surface-bright/10">
          <div className="text-lg font-bold text-foreground">
            ${skin.price.toLocaleString("en-US", { maximumFractionDigits: 2 })}
          </div>
        </div>

        {/* Buttons */}
        <div className="flex gap-2 mt-auto">
          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            onClick={() => onAddToCart(skin.id)}
            className="flex-shrink-0 w-10 h-10 rounded-md bg-surface-variant hover:bg-surface-bright/20 flex items-center justify-center text-primary transition-colors"
          >
            <ShoppingCart size={18} />
          </motion.button>
          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={() => onBuy(skin.id)}
            className="flex-1 py-2 bg-gradient-to-r from-blue-600 to-blue-700 hover:from-blue-700 hover:to-blue-800 text-white font-semibold rounded-md transition-all shadow-lg hover:shadow-xl"
          >
            Buy now
          </motion.button>
        </div>
      </div>
    </motion.div>
  );
}

function getBorderColor(borderClass: string): string {
  const colorMap: Record<string, string> = {
    "from-pink-500": "#ec4899",
    "from-yellow-500": "#eab308",
    "from-purple-500": "#a855f7",
    "from-lime-500": "#b4ec51",
    "from-blue-500": "#3b82f6",
    "from-rose-500": "#f43f5e",
    "from-green-500": "#22c55e",
    "from-indigo-500": "#6366f1",
  };
  return colorMap[borderClass] || "#b4ec51";
}
