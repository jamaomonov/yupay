import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Search,
  ShieldCheck,
  User as UserIcon,
} from "lucide-react";

import { Button, Input } from "@yupay/ui";

import { PageHeader } from "@/components/PageHeader";
import { DataTable, type Column } from "@/components/DataTable";
import { ApiError, api, apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

import type { UserAdminListOut, UserAdminOut } from "./types";

const PAGE_SIZE = 50;

export function UsersListPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<UserAdminOut | null>(null);

  // Tiny debounce so the table doesn't fire a request on every keystroke.
  useDebounce(search, 250, (v) => {
    setDebounced(v);
    setOffset(0);
  });

  const usersQuery = useQuery<UserAdminListOut>({
    queryKey: qk.users({ search: debounced || null, limit: PAGE_SIZE, offset }),
    queryFn: () => {
      const params = new URLSearchParams();
      if (debounced) params.set("search", debounced);
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(offset));
      return apiGet<UserAdminListOut>(`/api/v1/admin/users?${params.toString()}`);
    },
  });

  const setRoles = useMutation<
    UserAdminOut,
    ApiError,
    { id: string; roles: string[] }
  >({
    mutationFn: ({ id, roles }) =>
      api<UserAdminOut>(`/api/v1/admin/users/${id}/roles`, {
        method: "PATCH",
        body: JSON.stringify({ roles }),
      }),
    onSuccess: (updated) => {
      void qc.invalidateQueries({ queryKey: ["admin", "users"] });
      if (selected?.id === updated.id) setSelected(updated);
    },
  });

  const rows = usersQuery.data?.items ?? [];
  const total = usersQuery.data?.total ?? 0;
  const showingFrom = rows.length === 0 ? 0 : offset + 1;
  const showingTo = offset + rows.length;

  const columns: Column<UserAdminOut>[] = [
    {
      key: "user",
      header: "Пользователь",
      render: (u) => (
        <div className="flex items-center gap-3">
          {u.photo_url ? (
            <img
              src={u.photo_url}
              alt=""
              className="size-9 rounded-full object-cover border border-[--color-border] flex-shrink-0"
            />
          ) : (
            <div
              className="size-9 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0"
              style={{
                background: "var(--color-subtle)",
                color: "var(--color-muted)",
              }}
            >
              {initials(u.display_name)}
            </div>
          )}
          <div className="min-w-0">
            <div className="font-medium truncate">
              {u.display_name || u.email || u.id.slice(0, 8)}
            </div>
            <div className="text-xs text-[--color-muted] truncate">
              {u.email ?? `id ${u.id.slice(0, 8)}…`}
            </div>
          </div>
        </div>
      ),
    },
    {
      key: "tg",
      header: "Telegram",
      render: (u) =>
        u.telegram_link ? (
          <div className="flex flex-col text-xs">
            <code className="text-xs">@{u.telegram_link.tg_username ?? "—"}</code>
            <span className="text-[--color-muted]">
              tg_id {u.telegram_link.tg_user_id}
              {u.telegram_link.is_premium ? " · prem" : ""}
            </span>
          </div>
        ) : (
          <span className="text-xs text-[--color-muted]">—</span>
        ),
      className: "w-44",
    },
    {
      key: "roles",
      header: "Роли",
      render: (u) =>
        u.roles.length === 0 ? (
          <span className="text-xs text-[--color-muted]">user</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {u.roles.map((r) => (
              <span
                key={r}
                className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${
                  r === "admin"
                    ? "bg-amber-100 text-amber-700"
                    : "bg-zinc-100 text-zinc-700"
                }`}
              >
                {r}
              </span>
            ))}
          </div>
        ),
      className: "w-32",
    },
    {
      key: "locale",
      header: "Локаль",
      render: (u) => <code className="text-xs">{u.locale}</code>,
      className: "w-20",
    },
    {
      key: "created",
      header: "Зарег.",
      render: (u) =>
        new Date(u.created_at).toLocaleDateString("ru", {
          day: "2-digit",
          month: "2-digit",
          year: "2-digit",
        }),
      className: "w-24 text-right",
    },
  ];

  return (
    <div>
      <PageHeader
        title="Пользователи"
        description={`Всего: ${total}. Поиск по имени, email, Telegram username или tg_id.`}
      />

      <section className="mb-4">
        <div className="relative max-w-md">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[--color-muted]" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Поиск…"
            className="pl-9"
          />
        </div>
      </section>

      {usersQuery.isError && (
        <p className="text-sm text-[--color-danger] mb-3">
          Не удалось загрузить список.
        </p>
      )}

      <DataTable
        rows={rows}
        columns={columns}
        rowKey={(u) => u.id}
        onRowClick={(u) => setSelected(u)}
        empty={debounced ? "Под этот поиск пользователей нет." : "Пока никто не регистрировался."}
      />

      {total > PAGE_SIZE && (
        <div className="mt-4 flex items-center justify-between text-sm text-[--color-muted]">
          <span>
            {showingFrom}–{showingTo} из {total}
          </span>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              size="sm"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              <ChevronLeft className="size-4" />
              Назад
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={showingTo >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Вперёд
              <ChevronRight className="size-4" />
            </Button>
          </div>
        </div>
      )}

      {selected && (
        <UserDetailsDrawer
          user={selected}
          onClose={() => setSelected(null)}
          onToggleAdmin={(next) =>
            setRoles.mutate({
              id: selected.id,
              roles: next ? [...new Set([...selected.roles, "admin"])] : selected.roles.filter((r) => r !== "admin"),
            })
          }
          pending={setRoles.isPending}
        />
      )}
    </div>
  );
}

function UserDetailsDrawer({
  user,
  onClose,
  onToggleAdmin,
  pending,
}: {
  user: UserAdminOut;
  onClose: () => void;
  onToggleAdmin: (next: boolean) => void;
  pending: boolean;
}) {
  const isAdmin = user.roles.includes("admin");
  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-t-2xl sm:rounded-2xl bg-[--color-bg] border border-[--color-border] p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center gap-3">
          {user.photo_url ? (
            <img
              src={user.photo_url}
              alt=""
              className="size-12 rounded-full object-cover border border-[--color-border]"
            />
          ) : (
            <div className="size-12 rounded-full flex items-center justify-center bg-[--color-subtle] text-sm font-bold text-[--color-muted]">
              {initials(user.display_name)}
            </div>
          )}
          <div className="min-w-0">
            <h2 className="font-semibold truncate">
              {user.display_name || user.email || user.id.slice(0, 8)}
            </h2>
            <code className="block text-xs text-[--color-muted] truncate">
              {user.id}
            </code>
          </div>
        </header>

        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <Row label="Email" value={user.email ?? "—"} />
          <Row label="Локаль" value={user.locale} mono />
          <Row label="Зарегистрирован" value={formatDateTime(user.created_at)} />
          <Row label="Последнее обновление" value={formatDateTime(user.updated_at)} />
          {user.telegram_link && (
            <>
              <Row
                label="Telegram"
                value={
                  user.telegram_link.tg_username
                    ? `@${user.telegram_link.tg_username}`
                    : "—"
                }
              />
              <Row
                label="tg_user_id"
                value={String(user.telegram_link.tg_user_id)}
                mono
              />
              <Row
                label="Premium"
                value={user.telegram_link.is_premium ? "да" : "нет"}
              />
              <Row
                label="Последний вход"
                value={formatDateTime(user.telegram_link.last_seen_at)}
              />
            </>
          )}
        </dl>

        <section className="rounded-lg border border-[--color-border] p-3 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <ShieldCheck className="size-4 text-amber-500" />
              <span className="text-sm font-medium">Админ-доступ</span>
            </div>
            <Button
              size="sm"
              variant={isAdmin ? "danger" : "primary"}
              disabled={pending}
              onClick={() => {
                const action = isAdmin ? "снять админ-роль" : "выдать админ-роль";
                if (confirm(`Точно ${action} у пользователя ${user.display_name ?? user.id.slice(0, 8)}?`)) {
                  onToggleAdmin(!isAdmin);
                }
              }}
            >
              {pending ? "Сохраняем…" : isAdmin ? "Снять админа" : "Выдать админа"}
            </Button>
          </div>
          <p className="text-xs text-[--color-muted]">
            Админ-роль даёт доступ ко всем `/admin/*` эндпоинтам, включая денежные.
          </p>
        </section>

        <footer className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Закрыть
          </Button>
        </footer>
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <>
      <dt className="text-xs text-[--color-muted]">{label}</dt>
      <dd className={mono ? "font-mono text-xs" : "text-sm"}>{value}</dd>
    </>
  );
}

function initials(name: string | null): string {
  if (!name) return "👤";
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((s) => s[0]?.toUpperCase() ?? "")
      .join("") || "👤"
  );
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ru", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function useDebounce<T>(value: T, delayMs: number, callback: (v: T) => void): void {
  useEffect(() => {
    const id = setTimeout(() => callback(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs, callback]);
}

// Tiny visual import — kept for tree-shaking-friendly icon set.
const _icons = { UserIcon };
void _icons;
