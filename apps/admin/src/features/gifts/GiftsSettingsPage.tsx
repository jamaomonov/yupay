/**
 * Steam Gifts admin settings — one editable field (`margin_percent`) plus a
 * read-only view of the env-driven flag and region list.
 *
 * Mirrors the form pattern from `features/fx/FxRateCard.tsx`: a local state
 * mirror of the loaded value, `dirty`/`canSave` derived from the diff against
 * the query, and a save button disabled while a save is in flight.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { useEffect, useState } from "react";

import type { GiftsAdminSettings } from "./types";

import { PageHeader } from "@/components/PageHeader";
import { ErrorState, Spinner } from "@/components/States";
import { type ApiError, apiGet, apiPatch } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";
import { qk } from "@/lib/queryKeys";

const SETTINGS_PATH = "/api/v1/admin/gifts/settings";

export function GiftsSettingsPage() {
  const qc = useQueryClient();

  const query = useQuery<GiftsAdminSettings>({
    queryKey: qk.giftsSettings(),
    queryFn: () => apiGet<GiftsAdminSettings>(SETTINGS_PATH),
  });

  const [margin, setMargin] = useState("");

  // Re-mirror whenever the loaded (or just-saved) settings change — same
  // effect shape as `FxRateCard`.
  useEffect(() => {
    if (query.data) setMargin(query.data.margin_percent);
  }, [query.data]);

  const save = useMutation<GiftsAdminSettings, ApiError, string>({
    mutationFn: (value) =>
      apiPatch<GiftsAdminSettings>(
        SETTINGS_PATH,
        { margin_percent: value },
        { "Idempotency-Key": crypto.randomUUID() },
      ),
    onSuccess: (next) => {
      qc.setQueryData(qk.giftsSettings(), next);
    },
  });

  return (
    <div>
      <PageHeader title="Steam Гифты" description="Наценка и регионы каталога Steam-подарков." />

      {query.isLoading && <Spinner label="Загрузка…" />}

      {query.isError ? (
        <ErrorState
          description={extractApiMessage(query.error)}
          onRetry={() => void query.refetch()}
          retryPending={query.isFetching}
        />
      ) : null}

      {query.data ? (
        <SettingsCard
          settings={query.data}
          margin={margin}
          onMarginChange={setMargin}
          saving={save.isPending}
          error={save.isError ? extractApiMessage(save.error) : null}
          onSave={() => {
            const parsed = parseMargin(margin);
            if (parsed !== null) save.mutate(parsed);
          }}
        />
      ) : null}
    </div>
  );
}

interface SettingsCardProps {
  settings: GiftsAdminSettings;
  margin: string;
  onMarginChange: (value: string) => void;
  saving: boolean;
  error: string | null;
  onSave: () => void;
}

function SettingsCard({
  settings,
  margin,
  onMarginChange,
  saving,
  error,
  onSave,
}: SettingsCardProps) {
  const parsed = parseMargin(margin);
  const dirty = margin.trim() !== settings.margin_percent;
  const canSave = dirty && parsed !== null;

  return (
    <article className="max-w-xl rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
      <header className="mb-4 flex items-center justify-between gap-3">
        <h2 className="font-medium">Статус</h2>
        <span
          className={[
            "inline-block rounded-full px-2 py-0.5 text-xs font-medium",
            settings.enabled
              ? "bg-[var(--success)] text-[var(--success-fg)]"
              : "bg-[var(--bg-muted)] text-[var(--text-secondary)]",
          ].join(" ")}
        >
          {settings.enabled ? "Включено" : "Выключено"}
        </span>
      </header>
      <p className="mb-4 text-xs text-[var(--text-secondary)]">
        Флаг задаётся переменной окружения — здесь только для просмотра.
      </p>

      <div className="mb-4">
        <p className="mb-1 text-xs text-[var(--text-secondary)]">
          Регионы (по умолчанию — {settings.region_default})
        </p>
        <div className="flex flex-wrap gap-1.5">
          {settings.regions.map((zone) => (
            <span
              key={zone}
              className={[
                "inline-block rounded-full px-2 py-0.5 text-xs font-medium",
                zone === settings.region_default
                  ? "bg-[var(--bg-accent-soft)] text-[var(--accent-soft-fg)]"
                  : "bg-[var(--bg-muted)] text-[var(--text-secondary)]",
              ].join(" ")}
            >
              {zone}
            </span>
          ))}
        </div>
      </div>

      <label className="mb-3 block text-sm">
        <span className="mb-1 block text-xs text-[var(--text-secondary)]">Наценка, %</span>
        <Input
          inputMode="decimal"
          value={margin}
          onChange={(e) => {
            onMarginChange(e.target.value);
          }}
        />
      </label>

      {margin.trim() !== "" && parsed === null ? (
        <p className="mb-2 text-sm text-[var(--danger)]">Введите число от 0 до 100.</p>
      ) : null}

      {error ? <p className="mb-2 text-sm text-[var(--danger)]">{error}</p> : null}

      <Button onClick={onSave} disabled={saving || !canSave}>
        {saving ? "Сохраняем…" : "Сохранить"}
      </Button>
    </article>
  );
}

/** `null` for anything outside the 0–100 range the backend also enforces
 *  (`GiftsSettingsIn.margin_percent`, `ge=0, le=100`). */
function parseMargin(raw: string): string | null {
  const trimmed = raw.trim().replace(",", ".");
  if (trimmed === "") return null;
  const n = Number.parseFloat(trimmed);
  if (!Number.isFinite(n) || n < 0 || n > 100) return null;
  return trimmed;
}
