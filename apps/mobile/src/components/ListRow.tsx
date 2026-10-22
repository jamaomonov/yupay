import { ChevronRight, type LucideIcon } from "lucide-react-native";
import type { ReactNode } from "react";
import { Pressable, View } from "react-native";

import { T } from "@/components/ui";
import { useTheme } from "@/theme/ThemeProvider";

interface ListRowProps {
  Icon: LucideIcon;
  title: string;
  /** A second line under the title. */
  hint?: string;
  /** The current choice, right-aligned before the chevron. */
  value?: string;
  onPress?: () => void;
  /** Hides the top divider: the first row of a card. */
  first?: boolean;
  tone?: "fg" | "danger";
  trailing?: ReactNode;
}

/** A settings row: icon tile, title, optional value, chevron. */
export function ListRow({
  Icon,
  title,
  hint,
  value,
  onPress,
  first,
  tone = "fg",
  trailing,
}: ListRowProps) {
  const { c } = useTheme();
  const color = tone === "danger" ? c.danger : c.fg;
  return (
    <Pressable
      onPress={onPress}
      disabled={onPress === undefined}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        gap: 12,
        paddingHorizontal: 16,
        paddingVertical: 12,
        minHeight: 64,
        borderTopWidth: first === true ? 0 : 1,
        borderTopColor: c.border,
        opacity: pressed ? 0.7 : 1,
      })}
    >
      <View
        style={{
          width: 40,
          height: 40,
          borderRadius: 12,
          backgroundColor: c.muted,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Icon size={19} color={color} strokeWidth={1.8} />
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <T variant="h2" style={{ color }} numberOfLines={1}>
          {title}
        </T>
        {hint !== undefined && (
          <T variant="small" tone="mute" numberOfLines={1}>
            {hint}
          </T>
        )}
      </View>
      {value !== undefined && (
        <T tone="mute" numberOfLines={1}>
          {value}
        </T>
      )}
      {trailing}
      {onPress !== undefined && <ChevronRight size={18} color={c.dim} />}
    </Pressable>
  );
}
