/**
 * Display data for user and order ids a page already holds.
 *
 * The panel links to profiles and orders by raw UUID in fifteen places. An id
 * is not something an operator recognises, and the alternative to this hook —
 * widening fifteen DTOs and keeping their joins in step — is the version that
 * rots. One request per page instead.
 *
 * Ids are sorted into the query key so two renders with the same set share a
 * cache entry regardless of row order.
 */

import { useQuery } from "@tanstack/react-query";

import { apiGet } from "@/lib/api";

export interface UserRefData {
  id: string;
  name: string | null;
  photo_url: string | null;
}

export interface OrderRefData {
  id: string;
  image_url: string | null;
  label: string | null;
}

interface RefsOut {
  users: UserRefData[];
  orders: OrderRefData[];
}

export interface AdminRefs {
  user: (id: string | null | undefined) => UserRefData | undefined;
  order: (id: string | null | undefined) => OrderRefData | undefined;
}

/** Resolve the given ids. Empty lists make no request. */
export function useAdminRefs(
  userIds: (string | null | undefined)[],
  orderIds: (string | null | undefined)[] = [],
): AdminRefs {
  const users = [...new Set(userIds.filter((x): x is string => !!x))].sort();
  const orders = [...new Set(orderIds.filter((x): x is string => !!x))].sort();

  const q = useQuery<RefsOut>({
    queryKey: ["admin", "refs", users, orders],
    queryFn: () => {
      const params = new URLSearchParams();
      if (users.length) params.set("users", users.join(","));
      if (orders.length) params.set("orders", orders.join(","));
      return apiGet<RefsOut>(`/api/v1/admin/refs?${params.toString()}`);
    },
    enabled: users.length > 0 || orders.length > 0,
    // Names and avatars do not move; refetching them on every focus would be
    // one request per tab switch for data that is effectively static.
    staleTime: 5 * 60_000,
  });

  const userMap = new Map((q.data?.users ?? []).map((u) => [u.id, u]));
  const orderMap = new Map((q.data?.orders ?? []).map((o) => [o.id, o]));
  return {
    user: (id) => (id ? userMap.get(id) : undefined),
    order: (id) => (id ? orderMap.get(id) : undefined),
  };
}
