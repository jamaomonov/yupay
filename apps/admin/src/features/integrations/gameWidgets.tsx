/** G2B game-specific widgets used in the mapping wizard.
 *
 * - ``DenomPicker``: grid of denomination chips (lazy fetch on game change).
 * - ``RequiredFieldsHint``: read-only summary of what the player must enter
 *   at checkout for this game. Informational — surfaces the contract so
 *   admins don't ship a mapping that demands fields the storefront doesn't
 *   collect.
 * - ``PlayerChecker``: collapsed-by-default panel that proxies G2B's
 *   ``checkPlayerId`` so admins can verify a real player resolves before
 *   committing.
 */

import { useMutation, useQuery } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { AlertCircle, CheckCircle2, ChevronDown, ChevronUp, ScanFace } from "lucide-react";
import { useState } from "react";

import type { CheckPlayerResult, GameDenomList, GameDenomRow, GameFields } from "./types";

import { apiGet, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

// ---------------------------------------------------------------------------
// Denom picker
// ---------------------------------------------------------------------------

interface DenomPickerProps {
  gameCode: string | null;
  value: string;
  onChange: (catalogueName: string) => void;
}

export function DenomPicker({ gameCode, value, onChange }: DenomPickerProps) {
  const { data, isLoading, isError } = useQuery<GameDenomList>({
    queryKey: qk.g2bGameCatalogue(gameCode ?? ""),
    queryFn: () =>
      apiGet<GameDenomList>(
        `/api/v1/admin/integrations/g2b/games/${encodeURIComponent(gameCode ?? "")}/catalogue`,
      ),
    enabled: Boolean(gameCode),
    staleTime: 5 * 60_000,
  });

  if (!gameCode) {
    return (
      <p className="text-xs text-[var(--text-tertiary)]">
        Выберите игру выше, чтобы загрузить список номиналов.
      </p>
    );
  }
  if (isLoading) {
    return <p className="text-xs text-[var(--text-tertiary)]">Загружаем номиналы…</p>;
  }
  if (isError) {
    return <p className="text-xs text-[var(--danger)]">Не удалось загрузить каталог номиналов.</p>;
  }
  const items = data?.items ?? [];
  if (items.length === 0) {
    return (
      <div className="space-y-2">
        <p className="text-xs text-[var(--text-tertiary)]">
          У G2B нет публичного каталога для этой игры. Введите ``catalogue_name`` вручную:
        </p>
        <Input
          value={value}
          onChange={(e) => {
            onChange(e.target.value);
          }}
          placeholder="60 UC"
          className="font-mono text-sm"
        />
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div role="radiogroup" aria-label="Номинал" className="flex flex-wrap gap-2">
        {items.map((item) => (
          <DenomChip
            key={item.catalogue_name}
            item={item}
            selected={item.catalogue_name === value}
            onSelect={() => {
              onChange(item.catalogue_name);
            }}
          />
        ))}
      </div>
      <div className="flex items-center gap-2 text-xs text-[var(--text-tertiary)]">
        <span>Не нашли нужный?</span>
        <Input
          value={value}
          onChange={(e) => {
            onChange(e.target.value);
          }}
          placeholder="ввести вручную"
          className="h-7 max-w-40 font-mono text-xs"
        />
      </div>
    </div>
  );
}

function DenomChip({
  item,
  selected,
  onSelect,
}: {
  item: GameDenomRow;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={[
        "group flex flex-col items-start gap-0.5 rounded-md border px-3 py-1.5 text-left text-sm transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-base)]",
        selected
          ? "border-[var(--accent)] bg-[var(--bg-accent-soft)] text-[var(--accent-soft-fg)]"
          : "border-[var(--border-default)] bg-[var(--bg-surface)] hover:bg-[var(--bg-muted)]",
      ].join(" ")}
    >
      <span className="font-medium">{item.catalogue_name}</span>
      {item.price && (
        <span className="text-[10px] text-[var(--text-tertiary)] group-aria-checked:text-[var(--accent-soft-fg)]">
          ${item.price}
        </span>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Required fields hint
// ---------------------------------------------------------------------------

const FIELD_LABELS: Record<string, string> = {
  userid: "ID игрока",
  user_id: "ID игрока",
  player_id: "ID игрока",
  serverid: "Сервер",
  server_id: "Сервер",
  charname: "Имя персонажа",
};

export function RequiredFieldsHint({ gameCode }: { gameCode: string | null }) {
  const { data, isLoading } = useQuery<GameFields>({
    queryKey: qk.g2bGameFields(gameCode ?? ""),
    queryFn: () =>
      apiGet<GameFields>(
        `/api/v1/admin/integrations/g2b/games/${encodeURIComponent(gameCode ?? "")}/fields`,
      ),
    enabled: Boolean(gameCode),
    staleTime: 5 * 60_000,
  });

  if (!gameCode) return null;
  if (isLoading) {
    return <p className="text-xs text-[var(--text-tertiary)]">Загружаем требования игры…</p>;
  }
  const fields = data?.fields ?? [];
  if (fields.length === 0) {
    return (
      <p className="text-xs text-[var(--text-tertiary)]">
        G2B не сообщает требований для этой игры — миниапп будет спрашивать только ID игрока.
      </p>
    );
  }

  return (
    <div className="rounded-md border border-dashed border-[var(--border-default)] bg-[var(--bg-muted)] p-3">
      <div className="mb-1 text-[10px] uppercase tracking-wide text-[var(--text-tertiary)]">
        Клиент должен ввести при покупке
      </div>
      <ul className="flex flex-wrap gap-2 text-xs">
        {fields.map((f) => (
          <li
            key={f}
            className="rounded bg-[var(--bg-surface)] px-2 py-0.5 font-mono text-[var(--text-secondary)]"
          >
            {FIELD_LABELS[f] ?? f}
            <span className="ml-1 text-[10px] text-[var(--text-tertiary)]">({f})</span>
          </li>
        ))}
      </ul>
      {data?.notes && (
        <p className="mt-2 text-xs italic text-[var(--text-secondary)]">{data.notes}</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Player checker
// ---------------------------------------------------------------------------

export function PlayerChecker({ gameCode }: { gameCode: string | null }) {
  const [open, setOpen] = useState(false);
  const [playerId, setPlayerId] = useState("");
  const [serverId, setServerId] = useState("");
  const [charname, setCharname] = useState("");
  const [result, setResult] = useState<CheckPlayerResult | null>(null);
  const [checkFailed, setCheckFailed] = useState(false);

  const check = useMutation<CheckPlayerResult>({
    mutationFn: () =>
      apiPost<CheckPlayerResult>(
        `/api/v1/admin/integrations/g2b/games/${encodeURIComponent(gameCode ?? "")}/check-player`,
        {
          player_id: playerId.trim(),
          server_id: serverId.trim() || null,
          charname: charname.trim() || null,
        },
      ),
    onSuccess: (data) => {
      setCheckFailed(false);
      setResult(data);
    },
    onError: () => {
      // Don't fabricate a verdict: "the check didn't run" and "this player does
      // not exist" are opposite conclusions, and this widget exists precisely to
      // tell them apart. Faking `valid: false` made a network blip look like a
      // bad player id.
      setResult(null);
      setCheckFailed(true);
    },
  });

  if (!gameCode) return null;

  return (
    <section className="rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)]">
      <button
        type="button"
        onClick={() => {
          setOpen((o) => !o);
        }}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm font-medium"
      >
        <span className="flex items-center gap-2">
          <ScanFace className="size-4 text-[var(--accent)]" aria-hidden />
          Проверить игрока в G2B
          <span className="text-xs font-normal text-[var(--text-tertiary)]">
            опциональный диагностический шаг
          </span>
        </span>
        {open ? (
          <ChevronUp className="size-4 text-[var(--text-tertiary)]" aria-hidden />
        ) : (
          <ChevronDown className="size-4 text-[var(--text-tertiary)]" aria-hidden />
        )}
      </button>
      {open && (
        <div className="space-y-3 border-t border-[var(--border-subtle)] p-4">
          <p className="text-xs text-[var(--text-tertiary)]">
            G2B принимает заказы только на верифицированных игроков. Введите тестовый ID — мы
            спросим у G2B, существует ли такой игрок. Данные нигде не сохраняются.
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <FieldLabel label="ID игрока">
              <Input
                value={playerId}
                onChange={(e) => {
                  setPlayerId(e.target.value);
                }}
                placeholder="5679523421"
                className="font-mono"
              />
            </FieldLabel>
            <FieldLabel label="Сервер (если нужен)">
              <Input
                value={serverId}
                onChange={(e) => {
                  setServerId(e.target.value);
                }}
                placeholder="2001"
                className="font-mono"
              />
            </FieldLabel>
            <FieldLabel label="Charname (если нужен)">
              <Input
                value={charname}
                onChange={(e) => {
                  setCharname(e.target.value);
                }}
                placeholder=""
              />
            </FieldLabel>
          </div>
          <div className="flex items-center gap-3">
            <Button
              type="button"
              size="sm"
              onClick={() => {
                if (playerId.trim()) check.mutate();
              }}
              disabled={check.isPending || !playerId.trim()}
            >
              {check.isPending ? "Спрашиваем G2B…" : "Проверить"}
            </Button>
            {checkFailed && (
              <span
                role="alert"
                className="inline-flex items-center gap-1.5 rounded-full bg-[var(--bg-muted)] px-2.5 py-0.5 text-xs font-medium text-[var(--text-secondary)]"
              >
                Проверка не выполнена — повторите
              </span>
            )}
            {result && <ResultBadge result={result} />}
          </div>
        </div>
      )}
    </section>
  );
}

function FieldLabel({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[10px] uppercase tracking-wide text-[var(--text-tertiary)]">
        {label}
      </span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

function ResultBadge({ result }: { result: CheckPlayerResult }) {
  if (result.valid) {
    return (
      <span className="flex items-center gap-2 text-sm text-[var(--success-fg)]">
        <CheckCircle2 className="size-4" aria-hidden />
        Игрок найден{result.name ? `: ${result.name}` : ""}
      </span>
    );
  }
  return (
    <span className="flex items-center gap-2 text-sm text-[var(--danger)]">
      <AlertCircle className="size-4" aria-hidden />
      {result.reason ?? "не найден"}
    </span>
  );
}
