/**
 * Push notifications through Expo (ADR-0102): permission, the install's token registered with
 * `PUT /push/devices`, and the device dropped again on sign-out.
 *
 * The server pushes an order's outcome — delivered, failed, refunded, a top-up credited — with
 * `data = {type: "order", order_id}` on the Android channel `orders`.
 */
import Constants from "expo-constants";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";

import { newKey } from "@/lib/orders";
import { readPref, writePref } from "@/lib/prefs";
import { authRequest } from "@/lib/session";

const V1 = "/api/v1";
/** The id `PUT /push/devices` returned, so sign-out can remove this install. */
const DEVICE_KEY = "push.device";
/** The channel the server names in every Android message. */
const CHANNEL = "orders";

export type PushState = "granted" | "denied" | "ask" | "unsupported";

// A push that lands while the app is open still shows its banner.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

function projectId(): string | undefined {
  const extra: unknown = Constants.expoConfig?.extra;
  // `extra.eas.projectId` is written by `eas init` into app.json; read defensively.
  const eas = (extra as { eas?: { projectId?: unknown } } | undefined)?.eas;
  return typeof eas?.projectId === "string" ? eas.projectId : undefined;
}

/** Whether pushes can reach this install, and whether asking would still show the prompt. */
export async function pushState(): Promise<PushState> {
  if (Platform.OS === "web" || !Device.isDevice) return "unsupported";
  const perm = await Notifications.getPermissionsAsync();
  if (perm.granted) return "granted";
  return perm.canAskAgain ? "ask" : "denied";
}

/**
 * Registers this install for the signed-in account. `ask` shows the system prompt when it has
 * not been answered yet. Never throws: a phone that cannot be pushed is a quiet phone, not an
 * error on screen (Expo Go on Android, for one, has no remote pushes).
 */
export async function registerPush({
  ask,
  channelName,
}: {
  ask: boolean;
  /** The Android channel's name in the phone's settings, in the app's language. */
  channelName: string;
}): Promise<PushState> {
  try {
    let state = await pushState();
    if (state === "unsupported") return state;
    if (Platform.OS === "android") {
      await Notifications.setNotificationChannelAsync(CHANNEL, {
        name: channelName,
        importance: Notifications.AndroidImportance.HIGH,
        lightColor: "#AAFF33",
      });
    }
    if (state === "ask" && ask) {
      const answer = await Notifications.requestPermissionsAsync();
      state = answer.granted ? "granted" : answer.canAskAgain ? "ask" : "denied";
    }
    if (state !== "granted") return state;
    const id = projectId();
    if (id === undefined) return "unsupported";
    const token = (await Notifications.getExpoPushTokenAsync({ projectId: id })).data;
    const device = await authRequest<{ id: string }>(`${V1}/push/devices`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", "Idempotency-Key": newKey() },
      body: JSON.stringify({
        token,
        platform: Platform.OS === "ios" ? "ios" : "android",
        app_version: Constants.expoConfig?.version ?? null,
      }),
    });
    await writePref(DEVICE_KEY, device.id);
    return "granted";
  } catch {
    return "unsupported";
  }
}

/** Before sign-out: this install stops receiving the account's pushes. Never throws. */
export async function unregisterPush(): Promise<void> {
  const id = await readPref(DEVICE_KEY);
  if (id === null || id === "") return;
  try {
    await authRequest(`${V1}/push/devices/${encodeURIComponent(id)}`, {
      method: "DELETE",
      headers: { "Idempotency-Key": newKey() },
    });
  } catch {
    // The server moves the token to whoever signs in next anyway.
  }
  await writePref(DEVICE_KEY, "");
}
