import { motion, AnimatePresence } from "framer-motion";
import { Search, Layers, Info, Filter, X } from "lucide-react";
import { useState } from "react";

export interface FilterState {
  search: string;
  sortBy: "price-asc" | "price-desc" | "float-asc" | "float-desc" | "newest";
  conditions: ("FN" | "MW" | "FT" | "WW" | "BS")[];
}

interface SkinMarketFiltersProps {
  filters: FilterState;
  onFiltersChange: (filters: FilterState) => void;
  resultCount: number;
}

export default function SkinMarketFilters({
  filters,
  onFiltersChange,
  resultCount,
}: SkinMarketFiltersProps) {
  const [showFilters, setShowFilters] = useState(false);

  const handleSearch = (value: string) => {
    onFiltersChange({ ...filters, search: value });
  };

  const handleSort = (sortBy: FilterState["sortBy"]) => {
    onFiltersChange({ ...filters, sortBy });
  };

  const handleConditionToggle = (condition: "FN" | "MW" | "FT" | "WW" | "BS") => {
    const updatedConditions = filters.conditions.includes(condition)
      ? filters.conditions.filter((c) => c !== condition)
      : [...filters.conditions, condition];
    onFiltersChange({ ...filters, conditions: updatedConditions });
  };

  const handleReset = () => {
    onFiltersChange({
      search: "",
      sortBy: "newest",
      conditions: [],
    });
    setShowFilters(false);
  };

  const conditions = ["FN", "MW", "FT", "WW", "BS"] as const;

  return (
    <div className="sticky top-0 z-20 bg-background/95 backdrop-blur-sm border-b border-surface-bright/10 pb-4">
      {/* Search and Control Buttons */}
      <div className="px-4 pt-4 mb-4">
        <div className="flex gap-2">
          {/* Search Input */}
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-surface-bright/50 w-4 h-4" />
            <input
              type="text"
              placeholder="Search skins..."
              value={filters.search}
              onChange={(e) => handleSearch(e.target.value)}
              className="w-full bg-surface border border-surface-bright/20 rounded-md py-2.5 pl-10 pr-4 text-foreground placeholder-surface-bright/40 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors"
            />
          </div>

          {/* Control Buttons */}
          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            className="p-2.5 bg-surface border border-surface-bright/20 rounded-md hover:border-surface-bright/40 transition-colors flex items-center justify-center text-surface-bright/60 hover:text-surface-bright"
            title="Layers"
          >
            <Layers size={18} />
          </motion.button>

          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            className="p-2.5 bg-surface border border-surface-bright/20 rounded-md hover:border-surface-bright/40 transition-colors flex items-center justify-center text-surface-bright/60 hover:text-surface-bright"
            title="Info"
          >
            <Info size={18} />
          </motion.button>

          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            onClick={() => setShowFilters(!showFilters)}
            className={`p-2.5 bg-surface border rounded-md flex items-center justify-center transition-colors ${
              showFilters
                ? "border-primary bg-primary/10 text-primary"
                : "border-surface-bright/20 text-surface-bright/60 hover:text-surface-bright hover:border-surface-bright/40"
            }`}
            title="Filter"
          >
            <Filter size={18} />
          </motion.button>
        </div>
      </div>

      {/* Results Count */}
      <div className="px-4 text-xs text-surface-bright/60 mb-3">
        {resultCount} {resultCount === 1 ? "skin" : "skins"} found
      </div>

      {/* Filter Panel */}
      <AnimatePresence>
        {showFilters && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden border-t border-surface-bright/10 pt-4"
          >
            <div className="px-4 space-y-4">
              {/* Sort Options */}
              <div>
                <label className="text-xs font-semibold text-surface-bright/80 uppercase tracking-wide mb-2 block">
                  Sort By
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { value: "newest" as const, label: "Newest" },
                    { value: "price-asc" as const, label: "Price: Low" },
                    { value: "price-desc" as const, label: "Price: High" },
                    { value: "float-asc" as const, label: "Float: Low" },
                    { value: "float-desc" as const, label: "Float: High" },
                  ].map((option) => (
                    <motion.button
                      key={option.value}
                      whileHover={{ scale: 1.02 }}
                      whileTap={{ scale: 0.98 }}
                      onClick={() => handleSort(option.value)}
                      className={`py-2 px-3 rounded-md text-sm font-medium transition-all ${
                        filters.sortBy === option.value
                          ? "bg-primary text-background"
                          : "bg-surface border border-surface-bright/20 text-foreground hover:border-surface-bright/40"
                      }`}
                    >
                      {option.label}
                    </motion.button>
                  ))}
                </div>
              </div>

              {/* Condition Filter */}
              <div>
                <label className="text-xs font-semibold text-surface-bright/80 uppercase tracking-wide mb-2 block">
                  Condition
                </label>
                <div className="flex flex-wrap gap-2">
                  {conditions.map((condition) => (
                    <motion.button
                      key={condition}
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                      onClick={() => handleConditionToggle(condition)}
                      className={`py-2 px-4 rounded-md text-sm font-semibold transition-all ${
                        filters.conditions.includes(condition)
                          ? "bg-primary text-background"
                          : "bg-surface border border-surface-bright/20 text-foreground hover:border-surface-bright/40"
                      }`}
                    >
                      {condition}
                    </motion.button>
                  ))}
                </div>
              </div>

              {/* Reset Button */}
              <motion.button
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                onClick={handleReset}
                className="w-full py-2 px-4 bg-surface-variant/50 border border-surface-bright/20 rounded-md text-foreground text-sm font-medium hover:border-surface-bright/40 transition-colors flex items-center justify-center gap-2"
              >
                <X size={16} />
                Reset Filters
              </motion.button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
