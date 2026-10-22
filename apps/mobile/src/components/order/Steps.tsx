import { Check } from "lucide-react-native";
import { View } from "react-native";

import { T } from "@/components/ui";
import { useTheme } from "@/theme/ThemeProvider";

interface StepsProps {
  labels: readonly [string, string, string];
  /** 0: waiting for payment, 1: paid and being credited, 2: done. */
  at: 0 | 1 | 2;
}

/** Paid → crediting → done as a line of three dots: a wait feels shorter when it moves. */
export function Steps({ labels, at }: StepsProps) {
  const { c } = useTheme();
  return (
    <View style={{ flexDirection: "row", alignItems: "flex-start" }}>
      {labels.map((label, index) => {
        const done = index < at || at === 2;
        const current = index === at && at !== 2;
        const fill = done ? c.ok : current ? c.warn : c.muted;
        return (
          <View key={label} style={{ flex: 1, alignItems: "center", gap: 8 }}>
            <View style={{ flexDirection: "row", alignItems: "center", alignSelf: "stretch" }}>
              <View
                style={{
                  flex: 1,
                  height: 2,
                  backgroundColor: index === 0 ? "transparent" : index <= at ? c.ok : c.muted,
                }}
              />
              <View
                style={{
                  width: 24,
                  height: 24,
                  borderRadius: 12,
                  backgroundColor: fill,
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                {done && <Check size={14} color={c.card} strokeWidth={3} />}
              </View>
              <View
                style={{
                  flex: 1,
                  height: 2,
                  backgroundColor:
                    index === labels.length - 1 ? "transparent" : index < at ? c.ok : c.muted,
                }}
              />
            </View>
            <T
              variant="small"
              tone={done || current ? "fg" : "mute"}
              style={{ textAlign: "center" }}
            >
              {label}
            </T>
          </View>
        );
      })}
    </View>
  );
}
