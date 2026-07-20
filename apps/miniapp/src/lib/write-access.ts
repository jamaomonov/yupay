/**
 * "May the bot message you?" — asked once, at the moment it makes sense.
 *
 * Order status and delivered voucher codes go out over the bot. A customer who
 * opened the Mini App from a deep link and never pressed /start cannot be
 * written to, so their order completes into silence. Telegram can ask for that
 * permission (Bot API 6.9+), but only a native prompt, so we spend it wisely:
 * once, right before the first purchase, where the reason is self-evident.
 *
 * Never blocks checkout. A refusal — or an old client that cannot ask — just
 * means the customer reads their codes in the app instead.
 */

import { requestWriteAccess } from "./telegram";

const ASKED_KEY = "yupay.write-access-asked";

function alreadyAsked(): boolean {
  try {
    return localStorage.getItem(ASKED_KEY) === "1";
  } catch {
    // Private mode / storage disabled: treat as asked so a customer who can't
    // be remembered isn't prompted before every single order.
    return true;
  }
}

function rememberAsked(): void {
  try {
    localStorage.setItem(ASKED_KEY, "1");
  } catch {
    /* nothing to do — see alreadyAsked() */
  }
}

/**
 * Ask for write access unless we already have, resolving once the prompt is
 * done. Resolves `null` when nothing was asked (already asked, or unsupported).
 */
export async function ensureBotCanWrite(): Promise<boolean | null> {
  if (alreadyAsked()) return null;
  const granted = await requestWriteAccess();
  // `null` means the client never showed a prompt — leave the flag unset so a
  // newer client still gets its chance.
  if (granted === null) return null;
  rememberAsked();
  return granted;
}
