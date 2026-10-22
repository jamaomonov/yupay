import { router } from "expo-router";
import { ActivityIndicator, Pressable, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { TopBar } from "@/components/TopBar";
import { Button, Card, T } from "@/components/ui";
import { accountIds, spendable, useWallet, useWalletHistory } from "@/lib/account";
import { formatSum } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { historyRow, kindKey, type HistoryRow } from "@/lib/wallet";
import { useTheme } from "@/theme/ThemeProvider";
import { fonts, space } from "@/theme/tokens";

function Row({ row, first }: { row: HistoryRow; first: boolean }) {
  const { t, locale } = useI18n();
  const { c } = useTheme();
  const date = new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(row.at));
  const body = (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 12,
        paddingVertical: 12,
        paddingHorizontal: 16,
        borderTopWidth: first ? 0 : 1,
        borderTopColor: c.border,
      }}
    >
      <View style={{ flex: 1, gap: 2 }}>
        <T>{t(kindKey(row.kind))}</T>
        <T variant="small" tone="dim">
          {date}
        </T>
      </View>
      <T tone={row.delta >= 0 ? "ok" : "fg"} style={{ fontVariant: ["tabular-nums"] }}>
        {row.delta >= 0 ? "+" : "−"}
        {formatSum(Math.abs(row.delta))} {t("common.sum")}
      </T>
    </View>
  );
  const orderId = row.orderId;
  if (orderId === null) return body;
  return (
    <Pressable
      onPress={() => router.push({ pathname: "/order/[id]", params: { id: orderId } })}
      style={({ pressed }) => ({ opacity: pressed ? 0.7 : 1 })}
    >
      {body}
    </Pressable>
  );
}

/** The balance, «top up», and what moved it. */
export default function WalletScreen() {
  const { t } = useI18n();
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const wallet = useWallet();
  const history = useWalletHistory();
  const balance = spendable(wallet.data);
  const mine = accountIds(wallet.data);
  const rows = (history.data?.items ?? [])
    .map((tx) => historyRow(tx, mine))
    .filter((row): row is HistoryRow => row !== null);

  return (
    <ScrollView
      style={{ backgroundColor: c.bg }}
      contentContainerStyle={{
        paddingTop: insets.top + 4,
        paddingHorizontal: space.gutter,
        paddingBottom: 32,
        gap: 16,
      }}
    >
      <TopBar title={t("wallet.title")} fallback="/profile" />

      <Card style={{ padding: 16, gap: 14 }}>
        <View style={{ gap: 4 }}>
          <T tone="mute">{t("profile.balance")}</T>
          {balance === null ? (
            <ActivityIndicator color={c.mute} style={{ alignSelf: "flex-start" }} />
          ) : (
            <T
              style={{
                fontFamily: fonts.display,
                fontSize: 28,
                letterSpacing: -0.6,
                fontVariant: ["tabular-nums"],
              }}
            >
              {formatSum(balance)} {t("common.sum")}
            </T>
          )}
        </View>
        <Button label={t("wallet.topUp")} onPress={() => router.push("/topup")} />
      </Card>

      <View style={{ gap: 8 }}>
        <T variant="label" tone="mute">
          {t("wallet.history")}
        </T>
        {history.isLoading ? (
          <ActivityIndicator color={c.mute} />
        ) : history.isError ? (
          <T tone="mute">{t("common.loadError")}</T>
        ) : rows.length === 0 ? (
          <T tone="mute">{t("wallet.empty")}</T>
        ) : (
          <Card>
            {rows.map((row, i) => (
              <Row key={row.id} row={row} first={i === 0} />
            ))}
          </Card>
        )}
      </View>
    </ScrollView>
  );
}
