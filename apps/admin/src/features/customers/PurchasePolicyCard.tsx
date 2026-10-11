/**
 * Purchase policy on Customer 360: the account's lifetime purchase limit and the
 * trusted flag (`PUT /admin/users/{id}/purchase-policy`, orders.account_policy).
 *
 * Past the limit, a paid order is held for review instead of delivered — the
 * account's own orders and guest orders under its email, refunds excluded. A
 * trusted account skips every review rule and the pre-charge veto.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import type { UserAdminOut } from "@/features/users/types";

import { useToast } from "@/components/Toast";
import { type ApiError, api, formatApiError } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

interface PurchasePolicyCardProps {
  user: UserAdminOut;
}

interface PolicyBody {
  trusted: boolean;
  purchase_limit_usd: string | null;
}

export function PurchasePolicyCard({ user }: PurchasePolicyCardProps) {
  const qc = useQueryClient();
  const toast = useToast();
  const trusted = user.trusted_at !== null;
  const [limit, setLimit] = useState(user.purchase_limit_usd ?? "");
  useEffect(() => {
    setLimit(user.purchase_limit_usd ?? "");
  }, [user.purchase_limit_usd]);

  const save = useMutation<UserAdminOut, ApiError, PolicyBody>({
    mutationFn: (body) =>
      api<UserAdminOut>(`/api/v1/admin/users/${user.id}/purchase-policy`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      toast.success("Сохранено.");
      void qc.invalidateQueries({ queryKey: qk.customerOverview(user.id) });
      void qc.invalidateQueries({ queryKey: ["admin", "users"] });
    },
    onError: (err) => {
      toast.error(formatApiError(err));
    },
  });

  const cleaned = limit.trim().replace(",", ".");
  const limitValid = cleaned === "" || /^\d{1,10}(\.\d{1,2})?$/.test(cleaned);
  const limitChanged = cleaned !== (user.purchase_limit_usd ?? "").replace(/\.00$/, "");
  const current = cleaned === "" ? null : cleaned;

  return (
    <section className="space-y-3 rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
        Лимит покупок
      </h2>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <ShieldCheck
            className={
              trusted ? "size-4 text-[var(--success)]" : "size-4 text-[var(--text-secondary)]"
            }
            aria-hidden
          />
          <div className="min-w-0">
            <span className="text-sm font-medium">
              {trusted ? "Доверенный" : "Обычный покупатель"}
            </span>
            <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
              {trusted
                ? "Всё выдаётся сразу: без проверок и лимитов."
                : "Работают стандартные проверки."}
            </p>
          </div>
        </div>
        <Button
          size="sm"
          variant={trusted ? "secondary" : "primary"}
          disabled={save.isPending}
          onClick={() => {
            if (
              !trusted &&
              !window.confirm("Отметить доверенным? Все заказы будут выдаваться без проверок.")
            ) {
              return;
            }
            save.mutate({ trusted: !trusted, purchase_limit_usd: user.purchase_limit_usd });
          }}
        >
          {trusted ? "Снять отметку" : "Сделать доверенным"}
        </Button>
      </div>

      <form
        className="space-y-1.5 border-t border-[var(--border-subtle)] pt-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (!limitValid) return;
          save.mutate({ trusted, purchase_limit_usd: current });
        }}
      >
        <label htmlFor="purchase-limit" className="text-sm font-medium">
          Лимит, $ за всё время
        </label>
        <div className="flex gap-2">
          <Input
            id="purchase-limit"
            inputMode="decimal"
            placeholder="без лимита"
            value={limit}
            onChange={(e) => {
              setLimit(e.target.value);
            }}
            aria-invalid={!limitValid}
          />
          <Button type="submit" size="sm" disabled={!limitValid || !limitChanged || save.isPending}>
            {save.isPending ? "Сохраняем…" : "Сохранить"}
          </Button>
        </div>
        <p className="text-xs text-[var(--text-secondary)]">
          {trusted
            ? "У доверенного лимит не действует."
            : "Когда сумма покупок превысит лимит, следующий заказ уйдёт на проверку. Пусто — без лимита."}
        </p>
      </form>
    </section>
  );
}
