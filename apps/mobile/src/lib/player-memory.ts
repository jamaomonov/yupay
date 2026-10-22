/**
 * The player ID (and server) last bought for, per game, so the next purchase starts filled in.
 * Kept on the phone only (`prefs`: SecureStore), never sent anywhere.
 */
import { parseSaved } from "@/lib/player-fields";
import { readPref, writePref } from "@/lib/prefs";

/** SecureStore keys allow letters, digits, `.`, `-` and `_`; a slug already fits. */
function key(slug: string): string {
  return `player.${slug.replace(/[^\w.-]/g, "_")}`;
}

export async function loadPlayer(slug: string): Promise<Record<string, string>> {
  return parseSaved(await readPref(key(slug)));
}

export async function savePlayer(slug: string, fields: Record<string, string>): Promise<void> {
  const kept = parseSaved(JSON.stringify(fields));
  if (Object.keys(kept).length === 0) return;
  await writePref(key(slug), JSON.stringify(kept));
}
