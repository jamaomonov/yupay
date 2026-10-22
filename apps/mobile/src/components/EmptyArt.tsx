import type { LucideIcon } from "lucide-react-native";
import { View } from "react-native";
import Svg, { Circle, Defs, LinearGradient, Path, Stop } from "react-native-svg";

import { useTheme } from "@/theme/ThemeProvider";

const W = 168;
const H = 128;

/** A four-point sparkle centred on (x, y). */
function sparkle(x: number, y: number, r: number): string {
  const k = r * 0.28;
  return `M${x} ${y - r} Q${x + k} ${y - k} ${x + r} ${y} Q${x + k} ${y + k} ${x} ${y + r} Q${x - k} ${y + k} ${x - r} ${y} Q${x - k} ${y - k} ${x} ${y - r}Z`;
}

/**
 * The picture over an empty screen: the screen's own icon on a soft disc, with a few lime
 * sparkles. One drawing for every empty state, so they read as a family.
 */
export function EmptyArt({ Icon }: { Icon: LucideIcon }) {
  const { c, scheme } = useTheme();
  const ring = scheme === "dark" ? "rgba(255,255,255,0.06)" : "rgba(11,13,23,0.05)";
  return (
    <View style={{ width: W, height: H, alignItems: "center", justifyContent: "center" }}>
      <Svg width={W} height={H} style={{ position: "absolute" }}>
        <Defs>
          <LinearGradient id="disc" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={c.muted} stopOpacity="1" />
            <Stop offset="1" stopColor={c.muted} stopOpacity="0.35" />
          </LinearGradient>
        </Defs>
        <Circle cx={W / 2} cy={H / 2} r={60} fill={ring} />
        <Circle cx={W / 2} cy={H / 2} r={46} fill="url(#disc)" />
        <Circle cx={W / 2} cy={H / 2} r={30} fill={c.card} stroke={c.border} strokeWidth={1} />
        <Path d={sparkle(30, 30, 9)} fill={c.primary} />
        <Path d={sparkle(140, 92, 7)} fill={c.primary} opacity={0.8} />
        <Path d={sparkle(146, 26, 4)} fill={c.primary} opacity={0.6} />
        <Circle cx={24} cy={96} r={3} fill={c.primary} opacity={0.5} />
      </Svg>
      {/* Its own layer: an absolutely placed drawing paints over plain siblings on the web. */}
      <View style={{ zIndex: 1 }}>
        <Icon size={26} color={c.fg} strokeWidth={1.8} />
      </View>
    </View>
  );
}
