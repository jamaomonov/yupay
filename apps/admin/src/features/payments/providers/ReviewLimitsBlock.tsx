/**
 * Per-kassa spend limit in the provider drawer (`GET/PUT /admin/payments/review-limits`,
 * orders.provider_limit).
 *
 * One row per payment slug of this provider — Click has two kassas, the site's and the mini
 * app's, and they carry different risk. Past the limit a buyer's order waits for review and a
 * wallet top-up is not credited. The sum covers the buyer's payments through that kassa over
 * the window, so paying in parts does not get under it. Trusted accounts are exempt.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { useEffect, useRef, useState } from "react";

import { useToast } from "@/components/Toast";
import { type ApiError, api, apiGet, formatApiError } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

export interface ReviewLimit {
  provider: string;
  enabled: boolean;
  max_amount: string | null;
  currency: string;
  window_hours: number;
  changed_by: string | null;
  changed_at: string | null;
}

interface ReviewLimitList {
  items: ReviewLimit[];
}

interface Props {
  slugs: string[];
}

export function ReviewLimitsBlock({ slugs }: Props) {
  const query = useQuery<ReviewLimitList>({
    queryKey: qk.paymentReviewLimits(),
    queryFn: () => apiGet<ReviewLimitList>("/api/v1/admin/payments/review-limits"),
  });
  const rows = (query.data?.items ?? []).filter((row) => slugs.includes(row.provider));
  if (rows.length === 0) return null;

  return (
    <section className="space-y-3">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
        Лимит без проверки
      </h3>
      {rows.map((row) => (
        <LimitRow key={row.provider} row={row} />
      ))}
      <p className="text-xs text-[var(--text-secondary)]">
        Считается сумма оплат одного покупателя через кассу за окно: аккаунт, email, устройство и
        получатель. Оплата частями тоже суммируется. Выше лимита заказ ждёт проверки, пополнение
        кошелька не зачисляется. Доверенных не касается.
      </p>
    </section>
  );
}

function plain(amount: string | null): string {
  return amount === null ? "" : amount.replace(/\.0+$/, "");
}

function LimitRow({ row }: { row: ReviewLimit }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [enabled, setEnabled] = useState(row.enabled);
  const [amount, setAmount] = useState(plain(row.max_amount));
  const [hours, setHours] = useState(String(row.window_hours));
  // One key per intent: kept across a retry of the same save, renewed after it lands.
  const intent = useRef<string>(crypto.randomUUID());
  useEffect(() => {
    setEnabled(row.enabled);
    setAmount(plain(row.max_amount));
    setHours(String(row.window_hours));
  }, [row.enabled, row.max_amount, row.window_hours]);

  const save = useMutation<ReviewLimit, ApiError>({
    mutationFn: () =>
      api<ReviewLimit>(`/api/v1/admin/payments/review-limits/${row.provider}`, {
        method: "PUT",
        body: JSON.stringify({ enabled, max_amount: amount.trim(), window_hours: Number(hours) }),
        headers: { "Idempotency-Key": intent.current },
      }),
    onSuccess: () => {
      intent.current = crypto.randomUUID();
      toast.success("Лимит сохранён.");
      void qc.invalidateQueries({ queryKey: qk.paymentReviewLimits() });
    },
    onError: (err) => {
      toast.error(formatApiError(err));
    },
  });

  const amountValid = /^\d{1,12}$/.test(amount.trim()) && Number(amount) > 0;
  const hoursValid = /^\d{1,3}$/.test(hours.trim()) && Number(hours) >= 1 && Number(hours) <= 720;
  const changed =
    enabled !== row.enabled ||
    amount.trim() !== plain(row.max_amount) ||
    Number(hours) !== row.window_hours;
  const id = `limit-${row.provider}`;

  return (
    <form
      className="space-y-2 rounded-lg border border-[var(--border-subtle)] p-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (amountValid && hoursValid) save.mutate();
      }}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="font-mono text-sm">{row.provider}</span>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => {
              setEnabled(e.target.checked);
            }}
          />
          Включён
        </label>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <label htmlFor={`${id}-amount`} className="text-xs text-[var(--text-secondary)]">
            Больше, {row.currency === "UZS" ? "сум" : row.currency}
          </label>
          <Input
            id={`${id}-amount`}
            inputMode="numeric"
            placeholder="90000"
            value={amount}
            onChange={(e) => {
              setAmount(e.target.value.replace(/\s/g, ""));
            }}
            aria-invalid={amount !== "" && !amountValid}
          />
        </div>
        <div className="space-y-1">
          <label htmlFor={`${id}-hours`} className="text-xs text-[var(--text-secondary)]">
            Окно, часов
          </label>
          <Input
            id={`${id}-hours`}
            inputMode="numeric"
            value={hours}
            onChange={(e) => {
              setHours(e.target.value);
            }}
            aria-invalid={!hoursValid}
          />
        </div>
        <Button
          type="submit"
          size="sm"
          disabled={!amountValid || !hoursValid || !changed || save.isPending}
        >
          {save.isPending ? "Сохраняем…" : "Сохранить"}
        </Button>
      </div>
    </form>
  );
}
