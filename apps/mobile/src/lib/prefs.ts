/**
 * Small persisted preferences (theme, language).
 *
 * SecureStore on device; `localStorage` on the web preview, where SecureStore does not exist.
 * A failed read answers `null` and the caller falls back to its default.
 */
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

export async function readPref(key: string): Promise<string | null> {
  try {
    if (Platform.OS === "web") return globalThis.localStorage?.getItem(key) ?? null;
    return await SecureStore.getItemAsync(key);
  } catch {
    return null;
  }
}

export async function writePref(key: string, value: string): Promise<void> {
  try {
    if (Platform.OS === "web") globalThis.localStorage?.setItem(key, value);
    else await SecureStore.setItemAsync(key, value);
  } catch {
    // A preference that does not stick is not worth an error on screen.
  }
}
