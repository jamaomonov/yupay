import { router } from "expo-router";
import { History } from "lucide-react-native";
import { useState } from "react";
import { Pressable, RefreshControl, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { EmptyArt } from "@/components/EmptyArt";
import { TopBar } from "@/components/TopBar";
import { Button, Card, Skeleton, T } from "@/components/ui";
import { accountIds, spendable, useWallet, useWalletHistory } from "@/lib/account";
import { formatSum } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { historyRow, kindKey, type HistoryRow } from "@/lib/wallet";
import { useTheme } from "@/theme/ThemeProvider";
import { space } from "@/theme/tokens";

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
        <T variant="small" tone="mute">
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
  const [refreshing, setRefreshing] = useState(false);
  const refresh = async () => {
    setRefreshing(true);
    try {
      await Promise.all([wallet.refetch(), history.refetch()]);
    } finally {
      setRefreshing(false);
    }
  };
  const balance = spendable(wallet.data);
  const mine = accountIds(wallet.data);
  const rows = (history.data?.items ?? [])
    .map((tx) => historyRow(tx, mine))
    .filter((row): row is HistoryRow => row !== null);

  return (
    <ScrollView
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => void refresh()}
          tintColor={c.mute}
          colors={[c.fg]}
          progressBackgroundColor={c.card}
        />
      }
      style={{ backgroundColor: c.bg }}
      contentContainerStyle={{
        paddingTop: insets.top + 4,
        paddingHorizontal: space.gutter,
        paddingBottom: 32,
        gap: 16,
      }}
    >
      <TopBar title={t("wallet.title")} fallback="/profile" />

      <Card style={{ padding: 24, gap: 16 }}>
        <View style={{ gap: 4 }}>
          <T tone="mute">{t("profile.balance")}</T>
          {balance === null ? (
            <Skeleton style={{ width: 180, height: 32 }} />
          ) : (
            <T variant="display" style={{ fontVariant: ["tabular-nums"] }}>
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
          <Skeleton style={{ height: 200, borderRadius: 20 }} />
        ) : history.isError ? (
          <T tone="mute">{t("common.loadError")}</T>
        ) : rows.length === 0 ? (
          <Card style={{ padding: 24, alignItems: "center", gap: 12 }}>
            <EmptyArt Icon={History} />
            <T tone="mute">{t("wallet.empty")}</T>
          </Card>
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
