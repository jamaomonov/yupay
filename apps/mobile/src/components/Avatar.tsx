import { Image } from "expo-image";
import { View } from "react-native";

import { T } from "@/components/ui";
import { useTheme } from "@/theme/ThemeProvider";

/** Soft fills light enough for dark ink in either theme; the name picks one, so it never changes. */
const TINTS = ["#C7F27A", "#9FD8FF", "#FFC9A3", "#D9C2FF", "#FFE08A", "#A8EBD0"];

function tint(name: string): string {
  let sum = 0;
  for (const ch of name) sum += ch.codePointAt(0) ?? 0;
  return TINTS[sum % TINTS.length] ?? "#C7F27A";
}

interface AvatarProps {
  name: string;
  photoUrl: string | null;
  size?: number;
}

/** The account's picture, or its first letter on a circle tinted from the name. */
export function Avatar({ name, photoUrl, size = 56 }: AvatarProps) {
  const { c } = useTheme();
  const radius = size / 2;
  if (photoUrl !== null) {
    return (
      <Image
        source={photoUrl}
        style={{ width: size, height: size, borderRadius: radius, backgroundColor: c.muted }}
        contentFit="cover"
      />
    );
  }
  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius: radius,
        backgroundColor: tint(name),
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <T variant="title" style={{ fontSize: size * 0.4, lineHeight: size * 0.5, color: "#0B0D17" }}>
        {(name.trim()[0] ?? "Y").toUpperCase()}
      </T>
    </View>
  );
}
