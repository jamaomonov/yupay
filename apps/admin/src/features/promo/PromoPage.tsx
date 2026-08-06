import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input, Select } from "@yupay/ui";
import { Ban } from "lucide-react";
import { useState } from "react";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState } from "@/components/States";
import { useToast } from "@/components/Toast";
import { type ApiError, apiGet, apiPost } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";
import { formatMoney } from "@/lib/money";
import { qk } from "@/lib/queryKeys";

/** Mirrors the backend `PromoAdminOut`. */
interface PromoAdminOut {
  id: string;
  code: string;
  amount: string;
  currency: string;
  max_redemptions: number | null;
  redemptions: number;
  active: boolean;
  expires_at: string | null;
  created_at: string;
}

interface PromoListOut {
  items: PromoAdminOut[];
}

const CURRENCIES = ["UZS", "RUB", "USD", "USDT"] as const;

function fmtDate(iso: string): string {
  return new Intl.DateTimeFormat("ru", { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(iso),
  );
}

/** UTC ISO from a `datetime-local` value, or null when empty. */
function localToIso(local: string): string | null {
  if (!local) return null;
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

export function PromoPage() {
  const qc = useQueryClient();
  const toast = useToast();

  const listQuery = useQuery<PromoListOut>({
    queryKey: qk.promoCodes(),
    queryFn: () => apiGet<PromoListOut>("/api/v1/admin/promo"),
  });

  // --- issue form ---
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState<string>("UZS");
  const [code, setCode] = useState("");
  const [maxRedemptions, setMaxRedemptions] = useState("");
  const [expiresAt, setExpiresAt] = useState("");

  function resetForm() {
    setAmount("");
    setCode("");
    setMaxRedemptions("");
    setExpiresAt("");
  }

  const create = useMutation<PromoAdminOut, ApiError>({
    mutationFn: () =>
      apiPost<PromoAdminOut>(
        "/api/v1/admin/promo",
        {
          code: code.trim() ? code.trim() : null,
          amount,
          currency,
          max_redemptions: maxRedemptions.trim() ? Number(maxRedemptions) : null,
          expires_at: localToIso(expiresAt),
        },
        { "Idempotency-Key": crypto.randomUUID() },
      ),
    onSuccess: (promo) => {
      toast.success(`Код ${promo.code} выпущен`);
      resetForm();
      void qc.invalidateQueries({ queryKey: qk.promoCodes() });
    },
    onError: (err) => {
      toast.error(
        err.status === 409 ? "Код с таким значением уже существует" : "Не удалось выпустить код",
      );
    },
  });

  const deactivate = useMutation<PromoAdminOut, ApiError, string>({
    mutationFn: (id) => apiPost<PromoAdminOut>(`/api/v1/admin/promo/${id}/deactivate`, {}),
    onSuccess: (promo) => {
      toast.success(`Код ${promo.code} выключен`);
      void qc.invalidateQueries({ queryKey: qk.promoCodes() });
    },
    onError: () => {
      toast.error("Не удалось выключить код");
    },
  });

  const amountValid = Number(amount) > 0;
  const maxValid = maxRedemptions.trim() === "" || Number(maxRedemptions) > 0;
  const canSubmit = amountValid && maxValid && !create.isPending;

  const items = listQuery.data?.items ?? [];

  const columns: Column<PromoAdminOut>[] = [
    {
      key: "code",
      header: "Код",
      render: (p) => <code className="font-mono text-sm font-medium">{p.code}</code>,
      className: "w-48",
    },
    {
      key: "amount",
      header: "Номинал",
      render: (p) => <span className="font-mono">{formatMoney(p.amount, p.currency)}</span>,
      className: "w-36 text-right",
    },
    {
      key: "usage",
      header: "Активаций",
      render: (p) => (
        <span className="font-mono">
          {p.redemptions}
          {p.max_redemptions !== null ? ` / ${String(p.max_redemptions)}` : ""}
        </span>
      ),
      className: "w-28 text-right",
    },
    {
      key: "status",
      header: "Статус",
      render: (p) => <StatusBadge promo={p} />,
      className: "w-32",
    },
    {
      key: "expires_at",
      header: "Истекает",
      render: (p) => (
        <span className="text-[var(--text-secondary)]">
          {p.expires_at ? fmtDate(p.expires_at) : "—"}
        </span>
      ),
      className: "w-48",
    },
    {
      key: "created_at",
      header: "Создан",
      render: (p) => <span className="text-[var(--text-secondary)]">{fmtDate(p.created_at)}</span>,
      className: "w-48",
    },
    {
      key: "actions",
      header: "",
      render: (p) =>
        p.active ? (
          <Button
            variant="ghost"
            onClick={() => {
              deactivate.mutate(p.id);
            }}
            disabled={deactivate.isPending}
            aria-label={`Выключить ${p.code}`}
          >
            <Ban className="size-4" />
            Выключить
          </Button>
        ) : null,
      className: "w-40 text-right",
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Промокоды"
        description="Подарочные коды с фиксированным номиналом — начисляются сразу в кошелёк покупателя."
      />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (canSubmit) create.mutate();
        }}
        className="grid grid-cols-1 gap-4 rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)] md:grid-cols-2 lg:grid-cols-6"
      >
        <label className="flex flex-col gap-1 lg:col-span-1">
          <span className="text-sm font-medium">Номинал *</span>
          <Input
            type="number"
            inputMode="decimal"
            min="0"
            step="any"
            value={amount}
            placeholder="10000"
            onChange={(e) => {
              setAmount(e.target.value);
            }}
          />
        </label>

        <label className="flex flex-col gap-1 lg:col-span-1">
          <span className="text-sm font-medium">Валюта</span>
          <Select
            value={currency}
            onChange={(e) => {
              setCurrency(e.target.value);
            }}
            containerClassName="w-full"
          >
            {CURRENCIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
        </label>

        <label className="flex flex-col gap-1 lg:col-span-2">
          <span className="text-sm font-medium">Код</span>
          <Input
            value={code}
            placeholder="Пусто → сгенерируем"
            onChange={(e) => {
              setCode(e.target.value.toUpperCase());
            }}
          />
        </label>

        <label className="flex flex-col gap-1 lg:col-span-1">
          <span className="text-sm font-medium">Лимит активаций</span>
          <Input
            type="number"
            inputMode="numeric"
            min="1"
            value={maxRedemptions}
            placeholder="∞"
            onChange={(e) => {
              setMaxRedemptions(e.target.value);
            }}
          />
        </label>

        <label className="flex flex-col gap-1 lg:col-span-1">
          <span className="text-sm font-medium">Истекает</span>
          <Input
            type="datetime-local"
            value={expiresAt}
            onChange={(e) => {
              setExpiresAt(e.target.value);
            }}
          />
        </label>

        <div className="flex items-end lg:col-span-6">
          <Button type="submit" disabled={!canSubmit}>
            {create.isPending ? "Выпускаем…" : "Выпустить код"}
          </Button>
        </div>
      </form>

      {listQuery.isError ? (
        <ErrorState
          description={extractApiMessage(listQuery.error)}
          onRetry={() => void listQuery.refetch()}
          retryPending={listQuery.isFetching}
        />
      ) : (
        <DataTable
          rows={items}
          columns={columns}
          rowKey={(p) => p.id}
          loading={listQuery.isLoading}
          empty="Кодов пока нет — выпустите первый выше."
          ariaLabel="Промокоды"
          busy={listQuery.isFetching}
        />
      )}
    </div>
  );
}

function StatusBadge({ promo }: { promo: PromoAdminOut }) {
  const expired = promo.expires_at !== null && new Date(promo.expires_at).getTime() < Date.now();
  const exhausted = promo.max_redemptions !== null && promo.redemptions >= promo.max_redemptions;

  let label = "Активен";
  let cls = "bg-[var(--success)] text-[var(--success-fg)]";
  if (!promo.active) {
    label = "Выключен";
    cls = "bg-[var(--bg-muted)] text-[var(--text-secondary)]";
  } else if (expired) {
    label = "Истёк";
    cls = "bg-[var(--danger)] text-[var(--danger-fg)]";
  } else if (exhausted) {
    label = "Исчерпан";
    cls = "bg-[var(--danger)] text-[var(--danger-fg)]";
  }
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}
