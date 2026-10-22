import type { MeOut } from "@yupay/api-client/types";
import Constants from "expo-constants";
import * as Linking from "expo-linking";
import { router } from "expo-router";
import { ChevronRight, Gift, Globe, MessageCircle, Moon } from "lucide-react-native";
import { Pressable, View } from "react-native";

import { Avatar } from "@/components/Avatar";
import { ListRow } from "@/components/ListRow";
import { Screen } from "@/components/Screen";
import { Card, Skeleton, T } from "@/components/ui";
import { accountName, spendable, useWallet } from "@/lib/account";
import { formatSum } from "@/lib/format";
import { LOCALE_NAMES, useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { useTheme } from "@/theme/ThemeProvider";
import { radius } from "@/theme/tokens";

const SUPPORT_URL = "https://t.me/yupay_support";

/** Who is signed in and how; opens the account screen. */
function AccountCard({ user }: { user: MeOut }) {
  const { t } = useI18n();
  const { c } = useTheme();
  const name = accountName(user);
  return (
    <Card>
      <Pressable
        onPress={() => router.push("/account")}
        style={({ pressed }) => ({
          flexDirection: "row",
          alignItems: "center",
          gap: 16,
          padding: 16,
          opacity: pressed ? 0.7 : 1,
        })}
      >
        <Avatar name={name} photoUrl={user.photo_url} />
        <View style={{ flex: 1, gap: 4 }}>
          <T variant="amount" numberOfLines={1}>
            {name}
          </T>
          {user.sign_in_with != null && (
            <T tone="mute" numberOfLines={1}>
              {t(`profile.via.${user.sign_in_with}`)}
            </T>
          )}
        </View>
        <ChevronRight size={18} color={c.dim} />
      </Pressable>
    </Card>
  );
}

/** The spendable balance in soʻm; opens the wallet with its history and «top up». */
function BalanceCard() {
  const { t } = useI18n();
  const { c } = useTheme();
  const wallet = useWallet();
  const balance = spendable(wallet.data);
  return (
    <Card>
      <Pressable
        onPress={() => router.push("/wallet")}
        style={({ pressed }) => ({
          flexDirection: "row",
          alignItems: "center",
          padding: 20,
          opacity: pressed ? 0.7 : 1,
        })}
      >
        <View style={{ flex: 1, gap: 4 }}>
          <T tone="mute">{t("profile.balance")}</T>
          {balance === null ? (
            wallet.isError ? (
              <T tone="mute">—</T>
            ) : (
              <Skeleton style={{ width: 160, height: 32 }} />
            )
          ) : (
            <T variant="display" style={{ fontVariant: ["tabular-nums"] }}>
              {formatSum(balance)} {t("common.sum")}
            </T>
          )}
        </View>
        <View
          style={{
            height: 40,
            paddingHorizontal: 16,
            borderRadius: radius.control,
            backgroundColor: c.primary,
            justifyContent: "center",
          }}
        >
          <T variant="h2" style={{ color: c.primaryFg }}>
            {t("wallet.topUp")}
          </T>
        </View>
      </Pressable>
    </Card>
  );
}

export default function ProfileScreen() {
  const { t, locale } = useI18n();
  const { pref } = useTheme();
  const { user } = useSession();
  const version = Constants.expoConfig?.version ?? "";

  return (
    <Screen title={t("profile.title")}>
      <View style={{ gap: 12, marginTop: 8 }}>
        {user != null && <AccountCard user={user} />}
        <BalanceCard />

        <Card>
          <ListRow
            first
            Icon={Gift}
            title={t("profile.promo")}
            onPress={() => router.push("/promo")}
          />
        </Card>

        <Card>
          <ListRow
            first
            Icon={Globe}
            title={t("profile.language")}
            value={LOCALE_NAMES[locale]}
            onPress={() => router.push({ pathname: "/choose", params: { kind: "language" } })}
          />
          <ListRow
            Icon={Moon}
            title={t("profile.theme")}
            value={t(`profile.theme_${pref}`)}
            onPress={() => router.push({ pathname: "/choose", params: { kind: "theme" } })}
          />
          <ListRow
            Icon={MessageCircle}
            title={t("profile.support")}
            hint={t("profile.supportHint")}
            onPress={() => void Linking.openURL(SUPPORT_URL)}
          />
        </Card>
      </View>

      <T variant="small" tone="mute" style={{ textAlign: "center", marginTop: 24 }}>
        {t("profile.version", { version })}
      </T>
    </Screen>
  );
}
