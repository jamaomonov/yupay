/** Automatic failover switch (ADR-0108): a task a supplier refused, with the
 *  money back, moves once to the next cheapest supplier — if the margin holds. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { useEffect, useState } from "react";

import { useToast } from "@/components/Toast";
import { type ApiError, api, apiGet } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";

type FailoverMode = "off" | "retail" | "all";

interface SourcingSettings {
  failover_mode: FailoverMode;
  failover_min_margin_retail_pct: string;
  failover_min_margin_b2b_pct: string;
  failover_max_step_pct: string;
}

const KEY = ["admin", "sourcing", "settings"] as const;

const MODES: { value: FailoverMode; label: string; hint: string }[] = [
  { value: "off", label: "Выключено", hint: "Отказ поставщика — как раньше: оператор решает сам." },
  {
    value: "retail",
    label: "Только розница",
    hint: "Заказы покупателей уходят следующему поставщику. Реселлеры — как раньше.",
  },
  {
    value: "all",
    label: "Розница и реселлеры",
    hint: "Реселлерские заказы тоже, со своим порогом маржи.",
  },
];

export function FailoverSettingsCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const query = useQuery<SourcingSettings>({
    queryKey: KEY,
    queryFn: () => apiGet<SourcingSettings>("/api/v1/admin/sourcing/settings"),
  });
  const [draft, setDraft] = useState<SourcingSettings | null>(null);
  useEffect(() => {
    if (query.data) setDraft(query.data);
  }, [query.data]);

  const save = useMutation<SourcingSettings, ApiError, SourcingSettings>({
    mutationFn: (body) =>
      api<SourcingSettings>("/api/v1/admin/sourcing/settings", {
        method: "PATCH",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify(body),
      }),
    onSuccess: (data) => {
      toast.success("Сохранено");
      qc.setQueryData(KEY, data);
    },
    onError: (err) => {
      toast.error(extractApiMessage(err));
    },
  });

  if (!draft) return null;
  const set = (patch: Partial<SourcingSettings>) => {
    setDraft({ ...draft, ...patch });
  };
  const pct = (field: keyof SourcingSettings, label: string, help: string) => (
    <label className="block text-sm">
      <span className="mb-1 block font-medium">{label}</span>
      <input
        type="number"
        min={0}
        max={50}
        step="0.5"
        value={draft[field]}
        onChange={(e) => {
          set({ [field]: e.target.value });
        }}
        className="h-10 w-28 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3"
      />
      <span className="ml-2 text-[var(--text-tertiary)]">%</span>
      <span className="mt-1 block text-xs text-[var(--text-tertiary)]">{help}</span>
    </label>
  );

  return (
    <section className="space-y-4 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-5 shadow-[var(--shadow-sm)]">
      <div>
        <h2 className="text-base font-semibold">Автопередача при отказе поставщика</h2>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          Поставщик отказал и вернул деньги — задача один раз уходит самому дешёвому из других
          поставщиков этого SKU. Зависшие и неясные заказы не передаются никогда. Разовые пакеты не
          передаются: их отказ сразу возвращается на баланс.
        </p>
      </div>
      <div className="grid gap-2 md:grid-cols-3">
        {MODES.map((m) => (
          <label
            key={m.value}
            className={`cursor-pointer rounded-md border p-3 text-sm ${
              draft.failover_mode === m.value
                ? "border-[var(--accent)] bg-[var(--accent-subtle,transparent)]"
                : "border-[var(--border-default)]"
            }`}
          >
            <input
              type="radio"
              name="failover_mode"
              className="mr-2"
              checked={draft.failover_mode === m.value}
              onChange={() => {
                set({ failover_mode: m.value });
              }}
            />
            <span className="font-medium">{m.label}</span>
            <span className="mt-1 block text-xs text-[var(--text-tertiary)]">{m.hint}</span>
          </label>
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {pct(
          "failover_min_margin_retail_pct",
          "Мин. маржа, розница",
          "От суммы, которую заплатил покупатель.",
        )}
        {pct(
          "failover_min_margin_b2b_pct",
          "Мин. маржа, реселлеры",
          "0 — без убытка, но и без маржи.",
        )}
        {pct(
          "failover_max_step_pct",
          "Новый поставщик дороже не более",
          "Чем себестоимость у отказавшего.",
        )}
      </div>
      <Button
        disabled={save.isPending}
        onClick={() => {
          save.mutate(draft);
        }}
      >
        {save.isPending ? "Сохраняем…" : "Сохранить"}
      </Button>
    </section>
  );
}
