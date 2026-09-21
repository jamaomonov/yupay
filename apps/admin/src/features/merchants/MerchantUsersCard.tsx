import { useQuery } from "@tanstack/react-query";
import { Users } from "lucide-react";

import { T, fetchMerchantUsers, fill } from "./api";

import type { ApiError } from "@/lib/api";

import { extractApiMessage } from "@/lib/apiError";
import { qk } from "@/lib/queryKeys";

function moment(iso: string): string {
  return new Date(iso).toLocaleString("ru");
}

/**
 * Who can sign into this merchant's cabinet.
 *
 * Support's first question on "I cannot get in" is not the password: it is
 * whether the address was ever confirmed, and whether that person has ever
 * signed in at all. Those are three different conversations — never
 * confirmed, confirmed but never signed in, signed in last month and cannot
 * now — and before this card there was no screen that told them apart.
 *
 * `last_login_at` is derived from `merchant_sessions`, whose rows are written
 * at sign-in, so it cannot drift from the thing it describes.
 *
 * The addresses are PII. They are on an admin route and nowhere else, and
 * nothing in the path logs them.
 */
export function MerchantUsersCard({ merchantId }: { merchantId: string }) {
  const usersQuery = useQuery({
    queryKey: qk.merchantUsers(merchantId),
    queryFn: () => fetchMerchantUsers(merchantId),
  });
  const rows = usersQuery.data?.items ?? [];

  return (
    <section className="mb-6 rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
      <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold">
        <Users size={16} />
        {T.users.title}
      </h2>
      <p className="mb-3 text-xs text-[var(--text-secondary)]">{T.users.hint}</p>

      {usersQuery.isError && (
        <p className="text-xs text-[var(--danger-fg)]">
          {fill(T.users.loadError, { message: extractApiMessage(usersQuery.error as ApiError) })}
        </p>
      )}

      {!usersQuery.isLoading && !usersQuery.isError && rows.length === 0 && (
        <p className="text-sm text-[var(--text-secondary)]">{T.users.empty}</p>
      )}

      {rows.length > 0 && (
        <ul className="divide-y border-t">
          {rows.map((user) => (
            <li key={user.id} className="py-3">
              <p className="break-all text-sm font-medium">{user.email}</p>
              <p className="mt-0.5 text-xs">
                {user.email_confirmed_at === null ? (
                  // The most common cause of "I cannot log in", and the one
                  // a password reset does not touch.
                  <span className="text-[var(--danger-fg)]">{T.users.unconfirmed}</span>
                ) : (
                  <span className="text-[var(--text-secondary)]">
                    {fill(T.users.confirmed, { date: moment(user.email_confirmed_at) })}
                  </span>
                )}
              </p>
              <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
                {T.users.lastLogin}:{" "}
                {user.last_login_at === null ? T.users.neverLoggedIn : moment(user.last_login_at)}
              </p>
              <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
                {user.offer_accepted_at === null || user.offer_version === null
                  ? T.users.offerMissing
                  : fill(T.users.offerAccepted, {
                      date: moment(user.offer_accepted_at),
                      version: user.offer_version,
                    })}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
