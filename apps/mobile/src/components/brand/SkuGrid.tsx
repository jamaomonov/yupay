import type { SkuOut } from "@yupay/api-client/types";
import { Image } from "expo-image";
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
            style={{
              width: tile,
              alignItems: "center",
              gap: 4,
              paddingTop: 10,
              paddingBottom: 11,
              paddingHorizontal: 6,
              borderRadius: radius.tile,
              borderWidth: selected ? 2 : 1,
              borderColor: selected ? c.selBorder : c.border,
              backgroundColor: selected ? c.selBg : c.card,
              opacity: sku.in_stock ? 1 : 0.45,
            }}
          >
            <View style={{ width: 44, height: 44 }}>
              {sku.image_url !== null && (
                <Image
                  source={sku.image_url}
                  style={{ width: 44, height: 44 }}
                  contentFit="contain"
                />
              )}
            </View>
            <T variant="body" numberOfLines={1} style={{ fontSize: 13.5 }}>
              {sku.denomination ?? sku.sku_code}
            </T>
            <T
              variant="small"
              tone={selected ? "fg" : "mute"}
              style={{ fontVariant: ["tabular-nums"] }}
            >
              {sku.display_price ? formatSum(sku.display_price.amount) : "—"}
            </T>
          </Pressable>
        );
      })}
    </View>
  );
}
