/** Zustand store for the auth state. */

import { create } from "zustand";

import { clearTokens, getAccessToken, registerAuthBridge, setTokens } from "@/lib/api";

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
  setSession: (token: string, refreshToken: string | null) => void;
  setMe: (me: AuthMe | null) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthStore>((set) => ({
  token: getAccessToken(),
  me: null,
  setSession: (token, refreshToken) => {
    setTokens(token, refreshToken);
    set({ token });
  },
  setMe: (me) => {
    set({ me });
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
