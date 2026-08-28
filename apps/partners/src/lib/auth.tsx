"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { api, clearTokens, restore, setAccessToken } from "./api";

/**
 * Who is signed in, if anyone.
 *
 * `status` starts at `"loading"` and stays there until the stored refresh
 * token has been tried. That third state matters: without it every panel page
 * would see `null` on its first render and bounce a signed-in partner to the
 * login screen before the session had a chance to come back.
 */

export interface Partner {
  id: string;
  email: string;
  display_name: string | null;
  status: string;
}

type Status = "loading" | "in" | "out";

interface Session {
  status: Status;
  partner: Partner | null;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [partner, setPartner] = useState<Partner | null>(null);

  const load = useCallback(async () => {
    try {
      const me = await api<Partner>("/api/v1/affiliate/me");
      setPartner(me);
      setStatus("in");
    } catch {
      clearTokens();
      setPartner(null);
      setStatus("out");
    }
  }, []);

  useEffect(() => {
    // Whether there is a session to restore is a question only the HttpOnly
    // cookie can answer, so the only way to ask is to try.
    void (async () => {
      if (await restore()) await load();
      else setStatus("out");
    })();
  }, [load]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const tokens = await api<{ access_token: string }>("/api/v1/affiliate/auth/login", {
        method: "POST",
        body: { email, password },
        anonymous: true,
      });
      // The refresh token is not here and never will be — the response sets it
      // as an HttpOnly cookie.
      setAccessToken(tokens.access_token);
      await load();
    },
    [load],
  );

  const signOut = useCallback(async () => {
    // Best effort, and no body: the server reads the cookie and clears it. A
    // failed logout must still end the session locally — leaving a partner
    // apparently signed in because the server was unreachable is worse.
    try {
      await api("/api/v1/affiliate/auth/logout", { method: "POST", anonymous: true });
    } catch {
      // Ignored on purpose; see above.
    }
    clearTokens();
    setPartner(null);
    setStatus("out");
  }, []);

  return (
    <SessionContext.Provider value={{ status, partner, signIn, signOut }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): Session {
  const ctx = useContext(SessionContext);
  if (ctx === null) throw new Error("useSession must be used inside <SessionProvider>");
  return ctx;
}

/**
 * Send a signed-out visitor to the login page.
 *
 * Waits for `"loading"` to resolve before redirecting — a partner whose
 * session is still being restored is not signed out, they are not known yet.
 */
export function useRequireSession(): Session {
  const session = useSession();
  const router = useRouter();

  useEffect(() => {
    if (session.status === "out") router.replace("/login");
  }, [session.status, router]);

  return session;
}
