"use client";

import { useTranslations } from "next-intl";
import { useCallback } from "react";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
const GSI_SRC = "https://accounts.google.com/gsi/client";

interface TokenClient {
  requestAccessToken: () => void;
}

interface GoogleOauth2 {
  initTokenClient: (config: {
    client_id: string;
    scope: string;
    callback: (response: { access_token?: string }) => void;
  }) => TokenClient;
}

function oauth2(): GoogleOauth2 | undefined {
  // The gsi script's global — a known shape, typed here because Google ships no types.
  const g = (window as unknown as { google?: { accounts?: { oauth2?: GoogleOauth2 } } }).google;
  return g?.accounts?.oauth2;
}

interface GoogleButtonProps {
  /** Called with the popup's access token; nothing is called if they close it. */
  onToken: (accessToken: string) => void;
  disabled?: boolean;
  /** Runs before the popup opens; returning false stops it (e.g. offer not ticked). */
  beforeOpen?: () => boolean;
}

/**
 * «Продолжить с Google»: the OAuth token popup, as on yupay.uz (the same OAuth
 * client), so the button keeps our style. Renders nothing when the build has
 * no client id. The gsi script loads on the first press, not with the page.
 */
export function GoogleButton({ onToken, disabled = false, beforeOpen }: GoogleButtonProps) {
  const t = useTranslations("merchant.auth");

  const open = useCallback(() => {
    if (beforeOpen && !beforeOpen()) return;
    const start = () => {
      const client = oauth2();
      if (!client || !GOOGLE_CLIENT_ID) return;
      client
        .initTokenClient({
          client_id: GOOGLE_CLIENT_ID,
          scope: "openid email profile",
          callback: (response) => {
            if (response.access_token) onToken(response.access_token);
          },
        })
        .requestAccessToken();
    };
    if (document.querySelector(`script[src="${GSI_SRC}"]`)) {
      start();
      return;
    }
    const script = document.createElement("script");
    script.src = GSI_SRC;
    script.async = true;
    script.onload = start;
    document.head.appendChild(script);
  }, [beforeOpen, onToken]);

  if (!GOOGLE_CLIENT_ID) return null;
  return (
    <>
      <button
        type="button"
        onClick={open}
        disabled={disabled}
        className="border-border hover:bg-card-2 rounded-btn flex w-full items-center justify-center gap-2.5 border py-2.5 text-sm font-semibold disabled:opacity-60"
      >
        <GoogleIcon />
        {t("continueWithGoogle")}
      </button>
      <p className="text-tx-mute my-4 flex items-center gap-3 text-xs before:h-px before:flex-1 before:bg-current before:opacity-30 after:h-px after:flex-1 after:bg-current after:opacity-30">
        {t("orWithEmail")}
      </p>
    </>
  );
}

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.1a6.6 6.6 0 0 1 0-4.2V7.06H2.18a11 11 0 0 0 0 9.88l3.66-2.84z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38z"
      />
    </svg>
  );
}
