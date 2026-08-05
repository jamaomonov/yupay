/** Zustand store for the auth state. */

import { create } from "zustand";

import {
  clearTokens,
  getAccessToken,
  hasSessionHint,
  refreshAccessToken,
  registerAuthBridge,
  setTokens,
} from "@/lib/api";

interface AuthMe {
  id: string;
  email: string | null;
  display_name: string | null;
  photo_url: string | null;
  roles: string[];
}

interface AuthStore {
  token: string | null;
  me: AuthMe | null;
  /** False until the boot-time refresh-cookie re-hydration has settled. */
  bootstrapped: boolean;
  setSession: (token: string, refreshToken: string | null) => void;
  setMe: (me: AuthMe | null) => void;
  bootstrap: () => Promise<void>;
  logout: () => void;
}

export const useAuthStore = create<AuthStore>((set) => ({
  token: getAccessToken(),
  me: null,
  bootstrapped: false,
  setSession: (token, refreshToken) => {
    setTokens(token, refreshToken);
    set({ token });
  },
  setMe: (me) => {
    set({ me });
  },
  bootstrap: async () => {
    // The access token lives in memory only, so it's gone after a reload. If a
    // prior session hint exists, re-hydrate it from the HttpOnly refresh cookie
    // (refreshAccessToken pushes the new token in via the bridge) before the
    // router's AuthGuard decides logged-in vs login. No hint → stay logged out.
    if (!getAccessToken() && hasSessionHint()) {
      await refreshAccessToken();
    }
    set({ bootstrapped: true });
  },
  logout: () => {
    clearTokens();
    set({ token: null, me: null });
  },
}));

// Tell the API layer how to push token rotations / auth losses back
// into Zustand without ``api.ts`` importing the store (avoids a cycle).
registerAuthBridge({
  onTokensRotated: (access) => {
    useAuthStore.setState({ token: access });
  },
  onAuthLost: () => {
    useAuthStore.setState({ token: null, me: null });
  },
});

export type { AuthMe };
