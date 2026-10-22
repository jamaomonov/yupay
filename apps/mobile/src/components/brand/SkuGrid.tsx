import type { SkuOut } from "@yupay/api-client/types";
import { Image } from "expo-image";
import { Check } from "lucide-react-native";
import { Pressable, useWindowDimensions, View } from "react-native";

import { T } from "@/components/ui";
import { formatSum } from "@/lib/format";
import { useTheme } from "@/theme/ThemeProvider";
import { radius, space } from "@/theme/tokens";

const COLUMNS = 3;
const GAP = 8;

interface SkuGridProps {
  skus: readonly SkuOut[];
  selectedId: string | null;
  onSelect: (sku: SkuOut) => void;
}

/** Fixed denominations in three columns; a tile out of stock is shown but cannot be picked. */
export function SkuGrid({ skus, selectedId, onSelect }: SkuGridProps) {
  const { c } = useTheme();
  const { width } = useWindowDimensions();
  const tile = Math.floor(
    (Math.min(width, 430) - 2 * space.gutter - (COLUMNS - 1) * GAP) / COLUMNS,
  );

  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: GAP }}>
      {skus.map((sku) => {
        const selected = sku.id === selectedId;
        return (
          <Pressable
            key={sku.id}
            disabled={!sku.in_stock}
            onPress={() => onSelect(sku)}
            style={({ pressed }) => ({
              transform: [{ scale: pressed ? 0.97 : 1 }],
              width: tile,
              alignItems: "center",
              gap: 4,
              paddingTop: 12,
              paddingBottom: 12,
              paddingHorizontal: 8,
              borderRadius: radius.tile,
              borderWidth: selected ? 2 : 1,
              borderColor: selected ? c.selBorder : c.border,
              backgroundColor: selected ? c.selBg : c.card,
              opacity: sku.in_stock ? 1 : 0.45,
            })}
          >
            {selected && (
              <View
                style={{
                  position: "absolute",
                  top: 6,
                  right: 6,
                  width: 20,
                  height: 20,
                  borderRadius: 10,
                  backgroundColor: c.primary,
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <Check size={13} color={c.primaryFg} strokeWidth={3} />
              </View>
            )}
            <View style={{ width: 44, height: 44 }}>
              {sku.image_url !== null && (
                <Image
                  source={sku.image_url}
                  style={{ width: 44, height: 44 }}
                  contentFit="contain"
                />
              )}
            </View>
            <T variant="h2" numberOfLines={1}>
              {sku.denomination ?? sku.sku_code}
            </T>
            {/* The price in ink, not grey: it is half of what the buyer compares. */}
            <T style={{ fontVariant: ["tabular-nums"] }}>
              {sku.display_price ? formatSum(sku.display_price.amount) : "—"}
            </T>
          </Pressable>
        );
      })}
    </View>
  );
}
