import { useQueryClient } from "@tanstack/react-query";
import * as Notifications from "expo-notifications";
import { router } from "expo-router";
import { useEffect } from "react";

import { useI18n } from "@/lib/i18n";
import { registerPush } from "@/lib/push";
import { orderOf } from "@/lib/push-data";

/**
 * Mounted while signed in: registers this install for pushes (asking once), opens the order a
 * tapped push points at, and refreshes the account's orders and balance when one arrives.
 */
export function PushBridge() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const channelName = t("notifications.channel");
  const tapped = Notifications.useLastNotificationResponse();

  useEffect(() => {
    void registerPush({ ask: true, channelName });
  }, [channelName]);

  useEffect(() => {
    const sub = Notifications.addNotificationReceivedListener(() => {
      void queryClient.invalidateQueries({ queryKey: ["account"] });
    });
    return () => sub.remove();
  }, [queryClient]);

  useEffect(() => {
    const id = orderOf(tapped?.notification.request.content.data);
    if (id !== null) router.push({ pathname: "/order/[id]", params: { id } });
  }, [tapped]);

  return null;
}
