/**
 * USDT switch panel: mode, reseller allowlist and amount bounds, one save.
 * Local state syncs from this panel's own save response only, so a save
 * elsewhere on the page (a network card) never wipes edits typed here.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { useRef, useState } from "react";

import {
  parseUsdBound,
  saveSettings,
  T,
  usdtErrorMessage,
  type UsdtMode,
  type UsdtSettings,
} from "./api";

import type { ApiError } from "@/lib/api";

import { qk } from "@/lib/queryKeys";

const MODES: UsdtMode[] = ["off", "allowlist", "all"];
const S = T.settings;
const LABEL = "mb-1 block text-xs text-[var(--text-secondary)]";

function parseIds(raw: string): string[] {
  return raw
    .split(/[,\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

interface Props {
  settings: UsdtSettings;
}

export function UsdtSettingsPanel({ settings }: Props) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<UsdtMode>(settings.mode);
  const [allowlist, setAllowlist] = useState(settings.allowlist_merchant_ids.join(", "));
  const [min, setMin] = useState(settings.min_amount_usd);
  const [max, setMax] = useState(settings.max_amount_usd);
  const [saved, setSaved] = useState(false);

  const idemKey = useRef<string | null>(null);
  const minOk = parseUsdBound(min);
  const maxOk = parseUsdBound(max);

  const save = useMutation<UsdtSettings, ApiError>({
    mutationFn: () => {
      idemKey.current ??= crypto.randomUUID();
      return saveSettings(
        {
          mode,
          allowlist_merchant_ids: parseIds(allowlist),
          ...(minOk ? { min_amount_usd: minOk } : {}),
          ...(maxOk ? { max_amount_usd: maxOk } : {}),
        },
        idemKey.current,
      );
    },
    onSuccess: (next) => {
      idemKey.current = null;
      qc.setQueryData(qk.usdtSettings(), next);
      setMode(next.mode);
      setAllowlist(next.allowlist_merchant_ids.join(", "));
      setMin(next.min_amount_usd);
      setMax(next.max_amount_usd);
      setSaved(true);
    },
  });

  const edited =
    <V,>(set: (v: V) => void) =>
    (v: V) => {
      set(v);
      setSaved(false);
    };
  const noAddress =
    mode !== "off" && !settings.networks.some((n) => n.enabled && (n.address ?? "") !== "");

  return (
    <article
      onChange={() => {
        idemKey.current = null;
      }}
      className="mb-6 max-w-xl rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]"
    >
      <h2 className="mb-3 font-medium">{S.title}</h2>
      <label className="mb-3 block text-sm">
        <span className={LABEL}>{S.mode}</span>
        <select
          className="h-9 w-full rounded-md border bg-[var(--bg-surface)] px-2 text-sm"
          value={mode}
          onChange={(e) => {
            const next = MODES.find((m) => m === e.target.value);
            if (next) edited(setMode)(next);
          }}
        >
          {MODES.map((m) => (
            <option key={m} value={m}>
              {S.modes[m]}
            </option>
          ))}
        </select>
      </label>
      <label className="mb-3 block text-sm">
        <span className={LABEL}>{S.allowlist}</span>
        <textarea
          className="min-h-16 w-full rounded-md border bg-[var(--bg-surface)] p-2 font-mono text-xs"
          value={allowlist}
          onChange={(e) => {
            edited(setAllowlist)(e.target.value);
          }}
        />
      </label>
      {noAddress ? (
        <p role="status" className="mb-3 text-sm text-[var(--danger)]">
          {S.noAddress}
        </p>
      ) : null}
      <div className="mb-3 grid grid-cols-2 gap-3">
        <label className="block text-sm">
          <span className={LABEL}>{S.min}</span>
          <Input
            inputMode="decimal"
            value={min}
            onChange={(e) => {
              edited(setMin)(e.target.value);
            }}
          />
        </label>
        <label className="block text-sm">
          <span className={LABEL}>{S.max}</span>
          <Input
            inputMode="decimal"
            value={max}
            onChange={(e) => {
              edited(setMax)(e.target.value);
            }}
          />
        </label>
      </div>
      {!minOk || !maxOk ? <p className="mb-3 text-sm text-[var(--danger)]">{S.badAmount}</p> : null}
      {save.isError ? (
        <p role="alert" className="mb-2 text-sm text-[var(--danger)]">
          {usdtErrorMessage(save.error)}
        </p>
      ) : null}
      {saved ? <p className="mb-2 text-sm text-[var(--success-fg)]">{S.saved}</p> : null}
      <Button
        onClick={() => {
          save.mutate();
        }}
        disabled={save.isPending || !minOk || !maxOk}
      >
        {save.isPending ? S.saving : S.save}
      </Button>
    </article>
  );
}
