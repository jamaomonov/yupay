import { router } from "expo-router";
import { Bell, Search, type LucideIcon } from "lucide-react-native";
import { Pressable, View } from "react-native";

import { Avatar } from "@/components/Avatar";
import { T } from "@/components/ui";
import { accountName, spendable, useWallet } from "@/lib/account";
import { formatSum } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { useTheme } from "@/theme/ThemeProvider";
import { fonts, radius } from "@/theme/tokens";

function IconButton({
  Icon,
  label,
  onPress,
}: {
  Icon: LucideIcon;
  label: string;
  onPress: () => void;
}) {
  const { c } = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      style={({ pressed }) => ({
        width: 40,
        height: 40,
        borderRadius: radius.control,
        backgroundColor: c.muted,
        alignItems: "center",
        justifyContent: "center",
        opacity: pressed ? 0.7 : 1,
      })}
    >
      <Icon size={20} color={c.fg} />
    </Pressable>
  );
}

/** The home screen's top row: alerts and search (opens the catalogue), then the balance (opens the wallet) and the account (opens profile). */
export function HomeHeader() {
  const { t } = useI18n();
  const { c } = useTheme();
  const { user } = useSession();
  const wallet = useWallet();
  const balance = spendable(wallet.data);
  const name = user != null ? accountName(user) : "YuPay";

  return (
    <View
      style={{
        height: 52,
        flexDirection: "row",
        alignItems: "center",
        gap: 10,
        marginBottom: 8,
      }}
    >
      <IconButton
        Icon={Bell}
        label={t("notifications.title")}
        onPress={() => router.push("/notifications")}
      />
      <IconButton
        Icon={Search}
        label={t("home.search")}
        onPress={() => router.navigate("/catalog")}
      />

      <View style={{ flex: 1 }} />

      <Pressable
        accessibilityRole="button"
        accessibilityLabel={t("profile.balance")}
        onPress={() => router.push("/wallet")}
        style={({ pressed }) => ({
          height: 40,
          paddingHorizontal: 14,
          borderRadius: radius.control,
          backgroundColor: c.muted,
          justifyContent: "center",
          opacity: pressed ? 0.7 : 1,
        })}
      >
        <T style={{ fontFamily: fonts.semibold, fontVariant: ["tabular-nums"] }}>
          {balance === null ? "—" : formatSum(balance)} {t("common.sum")}
        </T>
      </Pressable>

      <Pressable
        accessibilityRole="button"
        accessibilityLabel={t("profile.title")}
        hitSlop={6}
        onPress={() => router.navigate("/profile")}
      >
        <Avatar name={name} photoUrl={user?.photo_url ?? null} size={40} />
      </Pressable>
    </View>
  );
}
