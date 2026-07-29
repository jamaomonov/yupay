/** User typeahead for the wallet lookup tab.
 *
 * Same shape as `SkuPicker` (see `features/integrations/pickers.tsx`): a
 * `Combobox` fed by a debounced query against the admin users search
 * endpoint — the same one `/users` uses — so an operator can find a user by
 * name / email / @username instead of having a UUID pre-copied. */

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import type { UserAdminListOut, UserAdminOut } from "@/features/users/types";

import { Combobox } from "@/components/Combobox";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { useDebouncedValue } from "@/lib/useDebouncedValue";

const RESULT_LIMIT = 10;

interface UserPickerProps {
  value: UserAdminOut | null;
  onChange: (next: UserAdminOut | null) => void;
  disabled?: boolean;
  id?: string;
}

export function UserPicker({ value, onChange, disabled, id }: UserPickerProps) {
  const [query, setQuery] = useState("");
  const debounced = useDebouncedValue(query, 200);

  // Only search once the operator has typed something — an unfiltered
  // `/admin/users` call would return an arbitrary page of the newest
  // signups, which isn't useful inside a picker.
  const { data, isLoading, isError } = useQuery<UserAdminListOut>({
    queryKey: qk.users({ search: debounced || null, limit: RESULT_LIMIT, offset: 0 }),
    queryFn: () => {
      const params = new URLSearchParams();
      params.set("search", debounced);
      params.set("limit", String(RESULT_LIMIT));
      return apiGet<UserAdminListOut>(`/api/v1/admin/users?${params.toString()}`);
    },
    enabled: debounced.trim().length > 0,
    staleTime: 30_000,
  });

  return (
    <Combobox
      id={id}
      ariaLabel="Пользователь"
      value={value}
      onChange={onChange}
      items={debounced.trim() ? (data?.items ?? []) : []}
      query={query}
      onQueryChange={setQuery}
      loading={isLoading}
      errorMessage={isError ? "Не удалось загрузить пользователей" : null}
      emptyMessage={
        debounced.trim() ? "Пользователи не найдены" : "Начни вводить имя, email или @username"
      }
      disabled={disabled}
      placeholder="Найти пользователя…"
      keyFor={(u) => u.id}
      renderSelected={(u) => <UserRow user={u} compact />}
      renderItem={(u) => <UserRow user={u} />}
    />
  );
}

function UserRow({ user, compact = false }: { user: UserAdminOut; compact?: boolean }) {
  const title = user.display_name || user.email || user.id.slice(0, 8);
  const tgUsername = user.telegram_link?.tg_username;
  if (compact) {
    return (
      <span className="flex min-w-0 items-center gap-2">
        <span className="min-w-0 truncate font-medium">{title}</span>
        <code className="shrink-0 text-[10px] text-[var(--text-tertiary)]">
          {user.id.slice(0, 8)}…
        </code>
      </span>
    );
  }
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-2">
        <span className="truncate font-medium">{title}</span>
        {user.deleted_at && (
          <span className="shrink-0 rounded bg-[var(--bg-muted)] px-1.5 py-0.5 text-[10px] text-[var(--danger-fg)]">
            удалён
          </span>
        )}
      </div>
      <div className="truncate text-xs text-[var(--text-secondary)]">
        {user.email ?? "без email"}
        {tgUsername ? ` · @${tgUsername}` : ""}
        {" · "}
        <code className="font-mono">{user.id.slice(0, 8)}…</code>
      </div>
    </div>
  );
}
