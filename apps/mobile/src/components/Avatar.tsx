import { Image } from "expo-image";
import { View } from "react-native";

import { T } from "@/components/ui";
import { useTheme } from "@/theme/ThemeProvider";

interface AvatarProps {
  name: string;
  photoUrl: string | null;
  size?: number;
}

/** The account's picture, or its first letter on a tile. */
export function Avatar({ name, photoUrl, size = 56 }: AvatarProps) {
  const { c } = useTheme();
  const radius = Math.round(size * 0.3);
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
        backgroundColor: c.muted,
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <T variant="title" style={{ fontSize: size * 0.36 }}>
        {(name.trim()[0] ?? "Y").toUpperCase()}
      </T>
    </View>
  );
}
