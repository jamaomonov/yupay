/** P2P switch panel: mode, merchant allowlist, HUMO bot id, owner id, connection status. */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { useEffect, useRef, useState } from "react";

import { saveSettings, T, p2pErrorMessage, type P2PMode, type P2PSettings } from "./api";

import type { ApiError } from "@/lib/api";

import { qk } from "@/lib/queryKeys";

const MODES: P2PMode[] = ["off", "allowlist", "all"];

const DIGITS = /^\d+$/;

/** Empty input clears the id; anything else is sent as a number. */
function idOrNull(raw: string): number | null {
  return raw.trim() === "" ? null : Number.parseInt(raw, 10);
}

function badId(raw: string): boolean {
  return raw.trim() !== "" && !DIGITS.test(raw.trim());
}

function parseIds(raw: string): string[] {
  return raw
    .split(/[,\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function P2PSettingsPanel({ settings }: { settings: P2PSettings }) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<P2PMode>(settings.mode);
  const [allowlist, setAllowlist] = useState(settings.allowlist_merchant_ids.join(", "));
  const [bot, setBot] = useState(settings.humo_bot_user_id?.toString() ?? "");
  const [owner, setOwner] = useState(settings.owner_telegram_user_id?.toString() ?? "");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setMode(settings.mode);
    setAllowlist(settings.allowlist_merchant_ids.join(", "));
    setBot(settings.humo_bot_user_id?.toString() ?? "");
    setOwner(settings.owner_telegram_user_id?.toString() ?? "");
  }, [settings]);

  const idemKey = useRef<string | null>(null);

  const save = useMutation<P2PSettings, ApiError>({
    mutationFn: () => {
      idemKey.current ??= crypto.randomUUID();
      return saveSettings(
        {
          mode,
          allowlist_merchant_ids: parseIds(allowlist),
          humo_bot_user_id: idOrNull(bot),
          owner_telegram_user_id: idOrNull(owner),
        },
        idemKey.current,
      );
    },
    onSuccess: (next) => {
      idemKey.current = null;
      qc.setQueryData(qk.p2pSettings(), next);
      setSaved(true);
    },
  });

  const idsInvalid = badId(bot) || badId(owner);
  const connection = settings.business_connection_id;
  const S = T.cards.settings;

  return (
    <article
      onChange={() => {
        idemKey.current = null;
      }}
      className="mb-6 max-w-xl rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]"
    >
      <h2 className="mb-3 font-medium">{S.title}</h2>
      <label className="mb-3 block text-sm">
        <span className="mb-1 block text-xs text-[var(--text-secondary)]">{S.mode}</span>
        <select
          className="h-9 w-full rounded-md border bg-[var(--bg-surface)] px-2 text-sm"
          value={mode}
          onChange={(e) => {
            const next = MODES.find((m) => m === e.target.value);
            if (next) setMode(next);
            setSaved(false);
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
        <span className="mb-1 block text-xs text-[var(--text-secondary)]">{S.allowlist}</span>
        <textarea
          className="min-h-16 w-full rounded-md border bg-[var(--bg-surface)] p-2 font-mono text-xs"
          value={allowlist}
          onChange={(e) => {
            setAllowlist(e.target.value);
            setSaved(false);
          }}
        />
      </label>
      <label className="mb-3 block text-sm">
        <span className="mb-1 block text-xs text-[var(--text-secondary)]">{S.humoBot}</span>
        <Input
          inputMode="numeric"
          value={bot}
          onChange={(e) => {
            setBot(e.target.value);
            setSaved(false);
          }}
        />
      </label>
      <label className="mb-3 block text-sm">
        <span className="mb-1 block text-xs text-[var(--text-secondary)]">{S.owner}</span>
        <Input
          inputMode="numeric"
          value={owner}
          onChange={(e) => {
            setOwner(e.target.value);
            setSaved(false);
          }}
        />
      </label>
      <p className="mb-3 text-sm">
        <span className="text-xs text-[var(--text-secondary)]">{S.connection}: </span>
        <span className={connection ? "text-[var(--success-fg)]" : "text-[var(--danger)]"}>
          {connection ? S.connected : S.notConnected}
        </span>
        {connection ? <code className="ml-2 font-mono text-xs">{connection}</code> : null}
      </p>
      {save.isError ? (
        <p role="alert" className="mb-2 text-sm text-[var(--danger)]">
          {p2pErrorMessage(save.error)}
        </p>
      ) : null}
      {saved ? <p className="mb-2 text-sm text-[var(--success-fg)]">{S.saved}</p> : null}
      <Button
        onClick={() => {
          save.mutate();
        }}
        disabled={save.isPending || idsInvalid}
      >
        {save.isPending ? S.saving : S.save}
      </Button>
    </article>
  );
}
