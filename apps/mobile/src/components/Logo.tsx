import { View } from "react-native";
import Svg, { Path } from "react-native-svg";

import { T } from "@/components/ui";
import { useTheme } from "@/theme/ThemeProvider";

/** The YuPay mark (`apps/web/public/logo/icon.svg`) beside the wordmark text. */
export function Logo() {
  const { c, scheme } = useTheme();
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
      <Svg width={24} height={22} viewBox="0 0 471.8 426.26">
        <Path
          fill={scheme === "dark" ? c.primary : c.fg}
          d="M0.06 23.83l0 294.05c0,0 -5.53,87.63 88.85,108.37l230.68 0c0,0 68.19,-17.67 80.63,-88.17l0 -210.84 71.58 0 -57.83 -63.63 -57.83 -63.63 -57.83 63.63 -57.83 63.63 71.57 0 0 183.78c0,0 -5.1,27.06 -30.74,27.06l-167.01 0c0,0 -26.08,-1.43 -26.08,-20.21l0 -294.05 -88.17 0z"
        />
      </Svg>
      <T variant="title" style={{ fontSize: 19 }}>
        YuPay
      </T>
    </View>
  );
}
