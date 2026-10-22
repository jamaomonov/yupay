import * as Haptics from "expo-haptics";
import type { LucideIcon } from "lucide-react-native";
import { useEffect, useState } from "react";
import { Animated, View } from "react-native";

interface StatusMarkProps {
  Icon: LucideIcon;
  color: string;
  background: string;
  /** Pops in with a success buzz: the order just landed. */
  celebrate: boolean;
}

/** The order's status icon. «Delivered» springs in once, with a haptic, the moment it lands. */
export function StatusMark({ Icon, color, background, celebrate }: StatusMarkProps) {
  const [scale] = useState(() => new Animated.Value(1));
  const [glow] = useState(() => new Animated.Value(0));
  const [ring] = useState(() => glow.interpolate({ inputRange: [0, 1], outputRange: [1, 1.5] }));

  useEffect(() => {
    if (!celebrate) return;
    void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    // From small, whether the screen opened delivered or watched it turn so.
    scale.setValue(0.4);
    Animated.parallel([
      Animated.spring(scale, { toValue: 1, friction: 4, tension: 120, useNativeDriver: true }),
      Animated.sequence([
        Animated.timing(glow, { toValue: 1, duration: 260, useNativeDriver: true }),
        Animated.timing(glow, { toValue: 0, duration: 700, useNativeDriver: true }),
      ]),
    ]).start();
  }, [celebrate, scale, glow]);

  return (
    <View style={{ width: 72, height: 72, alignItems: "center", justifyContent: "center" }}>
      <Animated.View
        style={{
          position: "absolute",
          width: 72,
          height: 72,
          borderRadius: 36,
          backgroundColor: background,
          opacity: glow,
          transform: [{ scale: ring }],
        }}
      />
      <Animated.View
        style={{
          width: 64,
          height: 64,
          borderRadius: 32,
          backgroundColor: background,
          alignItems: "center",
          justifyContent: "center",
          transform: [{ scale }],
        }}
      >
        <Icon size={30} color={color} />
      </Animated.View>
    </View>
  );
}
