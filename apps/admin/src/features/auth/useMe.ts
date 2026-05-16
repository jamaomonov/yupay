/** Hook that loads `/auth/me` and syncs it into the auth store. */

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";

import { apiGet, ApiError } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

import { useAuthStore, type AuthMe } from "./authStore";

export function useMe(enabled = true) {
  const token = useAuthStore((s) => s.token);
  const setMe = useAuthStore((s) => s.setMe);

  const query = useQuery<AuthMe>({
    queryKey: qk.me(),
    queryFn: () => apiGet<AuthMe>("/api/v1/auth/me"),
    enabled: enabled && !!token,
    retry: (failureCount, error) => {
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        return false;
      }
      return failureCount < 1;
    },
  });

  useEffect(() => {
    if (query.data) setMe(query.data);
  }, [query.data, setMe]);

  return query;
}
