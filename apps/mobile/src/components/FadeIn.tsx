import { useEffect, useState, type ReactNode } from "react";
import { Animated, type StyleProp, type ViewStyle } from "react-native";

interface FadeInProps {
  children: ReactNode;
  /** Milliseconds before it starts: a list staggers its rows with it. */
  delay?: number;
  style?: StyleProp<ViewStyle>;
}

/** Fades and lifts its content in once, when it first appears. */
export function FadeIn({ children, delay = 0, style }: FadeInProps) {
  const [shown] = useState(() => new Animated.Value(0));
  const [lift] = useState(() => shown.interpolate({ inputRange: [0, 1], outputRange: [8, 0] }));

  useEffect(() => {
    Animated.timing(shown, {
      toValue: 1,
      duration: 260,
      delay,
      useNativeDriver: true,
    }).start();
  }, [shown, delay]);

  return (
    <Animated.View style={[{ opacity: shown, transform: [{ translateY: lift }] }, style]}>
      {children}
    </Animated.View>
  );
}
