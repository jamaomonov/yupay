import { useQuery } from "@tanstack/react-query";
import { Button, Input, Select } from "@yupay/ui";
import { Ban, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import type { UserAdminListOut, UserAdminOut, UserAdminSort } from "./types";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { ErrorState } from "@/components/States";
import { apiGet } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { qk } from "@/lib/queryKeys";
import { useDebouncedValue } from "@/lib/useDebouncedValue";

const PAGE_SIZE = 50;

const SORT_OPTIONS: { value: UserAdminSort; label: string }[] = [
  { value: "created_desc", label: "Сначала новые" },
  { value: "created_asc", label: "Сначала старые" },
  { value: "wallet_desc", label: "Баланс: по убыванию" },
  { value: "wallet_asc", label: "Баланс: по возрастанию" },
  { value: "name_asc", label: "Имя: А → Я" },
  { value: "name_desc", label: "Имя: Я → А" },
];

/**
 * Users list — opening a row jumps straight to Customer 360 (`/customers/:id`),
 * where the full profile, recent activity, wallet, and role management live.
 *
 * Previously a row click opened a heavy drawer that duplicated half of the
 * Customer 360 page; that drawer is gone. The list keeps its compact columns
 * (avatar + name, Telegram link, current roles, locale, sign-up date) so an
 * operator can scan-and-filter before clicking through.
 */
export function UsersListPage() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState<UserAdminSort>("created_desc");
  // Tiny debounce so the table doesn't fire a request on every keystroke.
  const debounced = useDebouncedValue(search, 250);

  // Back to page one when the *search* or sort changes — an offset into the
  // previous result set means nothing against a different one.
  useEffect(() => {
    setOffset(0);
  }, [debounced, sort]);

  const usersQuery = useQuery<UserAdminListOut>({
    queryKey: qk.users({ search: debounced || null, sort, limit: PAGE_SIZE, offset }),
    queryFn: () => {
      const params = new URLSearchParams();
      if (debounced) params.set("search", debounced);
      params.set("sort", sort);
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(offset));
      return apiGet<UserAdminListOut>(`/api/v1/admin/users?${params.toString()}`);
    },
  });

  const rows = usersQuery.data?.items ?? [];
  const total = usersQuery.data?.total ?? 0;
  const walletTotals = usersQuery.data?.wallet_totals ?? [];
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
              className="size-9 flex-shrink-0 rounded-full border border-[var(--border-default)] object-cover"
            />
          ) : (
            <div
              className="flex size-9 flex-shrink-0 items-center justify-center rounded-full text-xs font-bold"
              style={{
                background: "var(--bg-muted)",
                color: "var(--text-secondary)",
              }}
            >
              {initials(u.display_name)}
            </div>
          )}
          <div className="min-w-0">
            <div className="truncate font-medium">
              {u.display_name ?? u.email ?? u.id.slice(0, 8)}
            </div>
            <div className="truncate text-xs text-[var(--text-secondary)]">
              {u.email ?? `id ${u.id.slice(0, 8)}…`}
            </div>
          </div>
        </div>
      ),
    },
    {
      key: "tg",
      header: "Провайдер",
      render: (u) =>
        u.telegram_link ? (
          <div className="flex flex-col text-xs">
            <code className="text-xs">@{u.telegram_link.tg_username ?? "—"}</code>
            <span className="text-[var(--text-secondary)]">
              tg_id {u.telegram_link.tg_user_id}
              {u.telegram_link.is_premium ? " · prem" : ""}
            </span>
          </div>
        ) : u.steam_link ? (
          <div className="flex flex-col text-xs">
            <code className="text-xs">{u.steam_link.persona_name ?? "Steam"}</code>
            <span className="text-[var(--text-secondary)]">steam {u.steam_link.steam_id}</span>
          </div>
        ) : u.email ? (
          <span className="text-xs text-[var(--text-secondary)]">email / google</span>
        ) : (
          <span className="text-xs text-[var(--text-secondary)]">—</span>
        ),
      className: "w-44",
    },
    {
      key: "roles",
      header: "Роли",
      // A suspension outranks the role badge here: an operator scanning the
      // list needs to know the account is cut off before anything else about
      // it, and a banned account has no role worth showing alongside.
      render: (u) =>
        u.banned_at !== null ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-[var(--danger-soft)] px-2 py-0.5 text-[10px] font-semibold uppercase text-[var(--danger-fg)]">
            <Ban className="size-3" aria-hidden />
            Заблокирован
          </span>
        ) : u.roles.length === 0 ? (
          <span className="text-xs text-[var(--text-secondary)]">user</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {u.roles.map((r) => (
              <span
                key={r}
                className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${
                  r === "admin"
                    ? "bg-[var(--warning-soft)] text-[var(--warning-fg)]"
                    : "bg-[var(--bg-muted)] text-[var(--text-secondary)]"
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
      key: "wallet",
      header: "Баланс",
      render: (u) =>
        u.wallet_balances.length === 0 ? (
          <span className="text-xs text-[var(--text-secondary)]">—</span>
        ) : (
          <div className="flex flex-col items-end gap-0.5 text-xs tabular-nums">
            {u.wallet_balances.map((w) => (
              <span key={w.currency}>{formatMoney(w.balance, w.currency)}</span>
            ))}
          </div>
        ),
      className: "w-36 text-right",
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
        description={`Всего: ${String(total)}. Поиск по имени, email, Telegram username/tg_id или Steam нику/steamid. Сумма на кошельках — все user_wallet, не фильтр.`}
      />

      <section className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard
          label="На кошельках (все)"
          value={
            walletTotals.length === 0 ? (
              "—"
            ) : (
              <div className="flex flex-col gap-1">
                {walletTotals.map((w) => (
                  <span key={w.currency}>{formatMoney(w.balance, w.currency)}</span>
                ))}
              </div>
            )
          }
          accent
        />
        <StatCard label="Пользователей" value={total} />
      </section>

      <section className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--text-secondary)]" />
          <Input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
            }}
            placeholder="Поиск…"
            className="pl-9"
          />
        </div>
        <Select
          aria-label="Сортировка"
          value={sort}
          onChange={(e) => {
            const next = SORT_OPTIONS.find((o) => o.value === e.target.value)?.value;
            if (next !== undefined) setSort(next);
          }}
          containerClassName="w-full sm:w-56"
        >
          {SORT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </Select>
      </section>

      {usersQuery.isError ? (
        <ErrorState
          title="Не удалось загрузить список"
          onRetry={() => void usersQuery.refetch()}
          retryPending={usersQuery.isFetching}
        />
      ) : (
        <DataTable
          rows={rows}
          columns={columns}
          rowKey={(u) => u.id}
          loading={usersQuery.isLoading}
          onRowClick={(u) => {
            void navigate(`/customers/${u.id}`);
          }}
          empty={debounced ? "Под этот поиск пользователей нет." : "Пока никто не регистрировался."}
        />
      )}

      {!usersQuery.isError && total > PAGE_SIZE && (
        <div className="mt-4 flex items-center justify-between text-sm text-[var(--text-secondary)]">
          <span>
            {showingFrom}–{showingTo} из {total}
          </span>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={offset === 0}
              onClick={() => {
                setOffset(Math.max(0, offset - PAGE_SIZE));
              }}
              aria-label="Предыдущая страница"
            >
              <ChevronLeft className="size-4" aria-hidden />
              Назад
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={showingTo >= total}
              onClick={() => {
                setOffset(offset + PAGE_SIZE);
              }}
              aria-label="Следующая страница"
            >
              Вперёд
              <ChevronRight className="size-4" aria-hidden />
            </Button>
          </div>
        </div>
      )}
    </div>
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
