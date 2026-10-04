/** P2P switch panel: mode, merchant allowlist, HUMO bot id. */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { useEffect, useState } from "react";

import { saveSettings, T, p2pErrorMessage, type P2PMode, type P2PSettings } from "./api";

import type { ApiError } from "@/lib/api";

import { qk } from "@/lib/queryKeys";

const MODES: P2PMode[] = ["off", "allowlist", "all"];

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
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setMode(settings.mode);
    setAllowlist(settings.allowlist_merchant_ids.join(", "));
    setBot(settings.humo_bot_user_id?.toString() ?? "");
  }, [settings]);

  const save = useMutation<P2PSettings, ApiError>({
    mutationFn: () =>
      saveSettings({
        mode,
        allowlist_merchant_ids: parseIds(allowlist),
        humo_bot_user_id: bot.trim() === "" ? null : Number.parseInt(bot, 10),
      }),
    onSuccess: (next) => {
      qc.setQueryData(qk.p2pSettings(), next);
      setSaved(true);
    },
  });

  const botInvalid = bot.trim() !== "" && !/^\d+$/.test(bot.trim());
  const S = T.cards.settings;

  return (
    <article className="mb-6 max-w-xl rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
      <h2 className="mb-3 font-medium">{S.title}</h2>
      <label className="mb-3 block text-sm">
        <span className="mb-1 block text-xs text-[var(--text-secondary)]">{S.mode}</span>
        <select
          className="h-9 w-full rounded-md border bg-[var(--bg-surface)] px-2 text-sm"
          value={mode}
          onChange={(e) => {
            setMode(e.target.value as P2PMode); // option values are the P2PMode literals
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
        disabled={save.isPending || botInvalid}
      >
        {save.isPending ? S.saving : S.save}
      </Button>
    </article>
  );
}
