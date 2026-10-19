import { useEffect, useState } from "react";
import { ActivityIndicator, Animated, Text, View } from "react-native";
import Svg, { Path } from "react-native-svg";

import { fonts } from "@/theme/tokens";

/** The native splash's colours, so the hand-over from it is invisible. */
const BG = "#060712";
const LIME = "#AAFF33";
const MUTE = "#9DA8C8";

interface LaunchProps {
  /** Set when the session could not be restored for want of a connection. */
  offline?: { text: string; retry: string; onRetry: () => void };
}

/**
 * What the app shows from the native splash until it knows who is signed in: the mark where
 * the splash had it, the wordmark fading in under it, a quiet spinner. Always dark, like the
 * splash, whatever the theme.
 */
export function Launch({ offline }: LaunchProps) {
  const [fade] = useState(() => new Animated.Value(0));
  useEffect(() => {
    Animated.timing(fade, { toValue: 1, duration: 420, useNativeDriver: true }).start();
  }, [fade]);

  return (
    <View style={{ flex: 1, backgroundColor: BG, alignItems: "center", justifyContent: "center" }}>
      <Svg width={76} height={69} viewBox="0 0 471.8 426.26">
        <Path
          fill={LIME}
          d="M0.06 23.83l0 294.05c0,0 -5.53,87.63 88.85,108.37l230.68 0c0,0 68.19,-17.67 80.63,-88.17l0 -210.84 71.58 0 -57.83 -63.63 -57.83 -63.63 -57.83 63.63 -57.83 63.63 71.57 0 0 183.78c0,0 -5.1,27.06 -30.74,27.06l-167.01 0c0,0 -26.08,-1.43 -26.08,-20.21l0 -294.05 -88.17 0z"
        />
      </Svg>
      <Animated.View style={{ opacity: fade, alignItems: "center", marginTop: 22, gap: 28 }}>
        <Text
          style={{ fontFamily: fonts.display, fontSize: 28, color: "#FFFFFF", letterSpacing: -0.6 }}
        >
          YuPay
        </Text>
        {offline === undefined ? (
          <ActivityIndicator color={MUTE} />
        ) : (
          <View style={{ alignItems: "center", gap: 14, paddingHorizontal: 32 }}>
            <Text
              style={{ fontFamily: fonts.medium, fontSize: 14, color: MUTE, textAlign: "center" }}
            >
              {offline.text}
            </Text>
            <Text
              onPress={offline.onRetry}
              style={{ fontFamily: fonts.semibold, fontSize: 15, color: LIME, padding: 8 }}
            >
              {offline.retry}
            </Text>
          </View>
        )}
      </Animated.View>
    </View>
  );
}
