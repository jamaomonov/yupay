"use client";

import { useLocale } from "next-intl";
import { useEffect, useRef } from "react";

import { useGoogleSignIn } from "@/hooks/useGoogleSignIn";

/**
 * Renders Google's official GIS button — the ID-token flow is only available
 * through their widget, exactly like Telegram's Login Widget next to it. The
 * button hands back a `credential` (a Google-signed JWT) which we POST to
 * /auth/google. Requires NEXT_PUBLIC_GOOGLE_CLIENT_ID; renders nothing (the
 * caller keeps its «скоро» tile) while it is unset.
 */

interface GsiApi {
  accounts: {
    id: {
      initialize: (config: {
        client_id: string;
        callback: (response: { credential: string }) => void;
      }) => void;
      renderButton: (el: HTMLElement, options: Record<string, unknown>) => void;
    };
  };
}

export function GoogleLoginButton() {
  const ref = useRef<HTMLDivElement>(null);
  const signInWithGoogle = useGoogleSignIn();
  const locale = useLocale();
  const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;

  useEffect(() => {
    const el = ref.current;
    if (!el || !clientId) return;

    const render = () => {
      const google = (window as unknown as { google?: GsiApi }).google;
      if (!google) return;
      google.accounts.id.initialize({
        client_id: clientId,
        callback: (response) => {
          signInWithGoogle(response.credential);
        },
      });
      google.accounts.id.renderButton(el, {
        theme: "filled_black",
        size: "large",
        text: "signin_with",
        shape: "rectangular",
        logo_alignment: "left",
        locale,
        // The grid cell is ~200px wide; GIS caps at 400 and centres itself.
        width: el.clientWidth || 200,
      });
    };

    const existing = document.querySelector<HTMLScriptElement>("script[data-gsi]");
    if (existing) {
      render();
      return () => {
        el.replaceChildren();
      };
    }
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.defer = true;
    s.dataset.gsi = "1";
    s.onload = render;
    document.head.appendChild(s);
    return () => {
      el.replaceChildren();
    };
  }, [clientId, locale, signInWithGoogle]);

  if (!clientId) return null;
  // min-height matches the ProviderButton tiles so the grid doesn't jump
  // while GIS paints its iframe into the slot.
  return <div ref={ref} className="flex min-h-[52px] items-center" />;
}
