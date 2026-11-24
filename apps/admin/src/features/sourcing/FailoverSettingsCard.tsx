/** Smart-sourcing switches (ADR-0108): automatic failover of refused tasks and
 *  the hourly automatic supplier choice, with its switch log. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { useEffect, useState } from "react";

import { useToast } from "@/components/Toast";
import { type ApiError, api, apiGet } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";

type FailoverMode = "off" | "retail" | "all";
type SmartMode = "off" | "shadow" | "on";

interface SourcingSettings {
  failover_mode: FailoverMode;
  failover_min_margin_retail_pct: string;
  failover_min_margin_b2b_pct: string;
  failover_max_step_pct: string;
  smart_mode: SmartMode;
  smart_switch_pct: string;
  smart_dwell_hours: number;
  smart_stock_step_pct: string;
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

const SMART_MODES: { value: SmartMode; label: string; hint: string }[] = [
  { value: "off", label: "Выключено", hint: "Маршруты стоят там, где их оставили." },
  {
    value: "shadow",
    label: "Только смотреть",
    hint: "Раз в час пишет в журнал, что переключил бы. Ничего не меняет.",
  },
  {
    value: "on",
    label: "Включено",
    hint: "Раз в час переводит SKU с «Автовыбором» на лучшего поставщика.",
  },
];

interface SwitchRow {
  sku_id: string;
  sku_code: string | null;
  label: string | null;
  from_supplier: string | null;
  to_supplier: string | null;
  from_cost_usdt: string | null;
  to_cost_usdt: string | null;
  reason: string;
  applied: boolean;
  created_at: string;
}

const REASONS: Record<string, string> = {
  cheaper: "дешевле",
  unavailable: "не может продать",
  blocked: "нет замены",
  suspicious: "подозрительно дешёво",
  verify_failed: "цена не подтвердилась",
};

function SwitchLog() {
  const query = useQuery<{ items: SwitchRow[] }>({
    queryKey: ["admin", "sourcing", "switches"],
    queryFn: () => apiGet<{ items: SwitchRow[] }>("/api/v1/admin/sourcing/switches?limit=50"),
  });
  const rows = query.data?.items ?? [];
  return (
    <div className="border-t border-[var(--border-subtle)] pt-4">
      <h3 className="text-sm font-semibold">Журнал переключений</h3>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm text-[var(--text-tertiary)]">Пока пусто.</p>
      ) : (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-[var(--text-tertiary)]">
              <tr>
                <th className="py-1 pr-3">Когда</th>
                <th className="py-1 pr-3">SKU</th>
                <th className="py-1 pr-3">Откуда → куда</th>
                <th className="py-1 pr-3">Цена, $</th>
                <th className="py-1 pr-3">Почему</th>
                <th className="py-1">Сделано</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={`${r.sku_id}-${r.created_at}`}
                  className="border-t border-[var(--border-subtle)]"
                >
                  <td className="whitespace-nowrap py-1 pr-3">
                    {new Date(r.created_at).toLocaleString("ru-RU")}
                  </td>
                  <td className="py-1 pr-3">{r.label ?? r.sku_code ?? r.sku_id}</td>
                  <td className="py-1 pr-3">
                    {r.from_supplier ?? "—"} → {r.to_supplier ?? "—"}
                  </td>
                  <td className="whitespace-nowrap py-1 pr-3">
                    {r.from_cost_usdt ?? "—"} → {r.to_cost_usdt ?? "—"}
                  </td>
                  <td className="py-1 pr-3">{REASONS[r.reason] ?? r.reason}</td>
                  <td className="py-1">{r.applied ? "да" : "нет (наблюдение)"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

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
          set({ [field]: field === "smart_dwell_hours" ? Number(e.target.value) : e.target.value });
        }}
        className="h-10 w-28 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3"
      />
      <span className="ml-2 text-[var(--text-tertiary)]">
        {field === "smart_dwell_hours" ? "ч" : "%"}
      </span>
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
      <div className="border-t border-[var(--border-subtle)] pt-4">
        <h2 className="text-base font-semibold">Автовыбор поставщика</h2>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          Для SKU с отметкой «Автовыбор» (ставится на странице «Сравнить поставщиков по бренду») раз
          в час выбирает самого дешёвого поставщика, который может продать. Закреплённые вручную
          правила не трогает. Поставщик, который трижды за сутки не справился с SKU, уходит в
          карантин на 6 часов (потом 12 и 24).
        </p>
      </div>
      <div className="grid gap-2 md:grid-cols-3">
        {SMART_MODES.map((m) => (
          <label
            key={m.value}
            className={`cursor-pointer rounded-md border p-3 text-sm ${
              draft.smart_mode === m.value
                ? "border-[var(--accent)]"
                : "border-[var(--border-default)]"
            }`}
          >
            <input
              type="radio"
              name="smart_mode"
              className="mr-2"
              checked={draft.smart_mode === m.value}
              onChange={() => {
                set({ smart_mode: m.value });
              }}
            />
            <span className="font-medium">{m.label}</span>
            <span className="mt-1 block text-xs text-[var(--text-tertiary)]">{m.hint}</span>
          </label>
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {pct("smart_switch_pct", "Переключать, если дешевле на", "Защита от скачков на курсе.")}
        {pct(
          "smart_dwell_hours",
          "Не переключать обратно раньше",
          "Если поставщик не может продать — сразу.",
        )}
        {pct(
          "smart_stock_step_pct",
          "Нет в наличии — брать дороже не более",
          "Дороже — остаётся на месте, в журнале «нет замены».",
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
      <SwitchLog />
    </section>
  );
}
