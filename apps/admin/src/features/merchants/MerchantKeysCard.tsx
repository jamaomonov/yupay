import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useId, useRef, useState } from "react";

import {
  T,
  createApiKey,
  fetchApiKeys,
  fill,
  putIpAllowlist,
  revokeApiKey,
  type ApiKeyCreatedOut,
  type ApiKeyOut,
  type MerchantOut,
} from "./api";
import { CopyValue } from "./CopyValue";

import type { ApiError } from "@/lib/api";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useToast } from "@/components/Toast";
import { extractApiMessage } from "@/lib/apiError";
import { qk } from "@/lib/queryKeys";

/** The admin renders dates in `ru` everywhere; `MerchantDetail` does the
 *  same inline. One helper here rather than four call sites. */
function moment(iso: string): string {
  return new Date(iso).toLocaleString("ru");
}

/**
 * A merchant's machine credentials, from the operator's side.
 *
 * The endpoints behind this card — issue, list, revoke — shipped with the
 * B2B milestone and had no button anywhere. The cost was concrete: a
 * merchant sent us `ypms…` as their key id, and support could not see
 * whether the account had a live key at all, when it was last used, or
 * whether an IP allowlist was turning their requests away. Every one of
 * those questions is a column here.
 *
 * Since ADR-0103 a new key is one string, `ypk_…`, and the IP allowlist is the
 * merchant's — one list for every key, edited here and in the cabinet.
 *
 * Revoked keys stay in the list, as the API intends: "which credential was
 * live when this broke" is a question that only an unfiltered list answers.
 */
interface MerchantKeysCardProps {
  merchant: MerchantOut;
  /** The list query caches the merchant row; the saved row replaces it there. */
  onChange: (next: MerchantOut) => void;
}

export function MerchantKeysCard({ merchant, onChange }: MerchantKeysCardProps) {
  const merchantId = merchant.id;
  const qc = useQueryClient();
  const toast = useToast();
  const labelFieldId = useId();
  const ipFieldId = useId();

  const [label, setLabel] = useState("");
  const [allowlist, setAllowlist] = useState((merchant.api_ip_allowlist ?? []).join("\n"));
  const [issued, setIssued] = useState<ApiKeyCreatedOut | null>(null);
  const [confirming, setConfirming] = useState<ApiKeyOut | null>(null);
  const createKey = useRef("");
  const revokeKey = useRef("");

  const keysQuery = useQuery({
    queryKey: qk.merchantKeys(merchantId),
    queryFn: () => fetchApiKeys(merchantId),
  });

  const create = useMutation<ApiKeyCreatedOut, ApiError>({
    mutationFn: () => createApiKey(merchantId, { label }, createKey.current),
    onSuccess: (key) => {
      setIssued(key);
      setLabel("");
      void qc.invalidateQueries({ queryKey: qk.merchantKeys(merchantId) });
    },
    onError: (err) => {
      toast.error(fill(T.keys.createError, { message: extractApiMessage(err) }));
    },
  });

  const saveIps = useMutation<MerchantOut, ApiError>({
    // Blank lines and stray spaces are the ordinary result of pasting a list.
    mutationFn: () =>
      putIpAllowlist(
        merchantId,
        allowlist
          .split("\n")
          .map((line) => line.trim())
          .filter((line) => line !== ""),
      ),
    onSuccess: (next) => {
      setAllowlist((next.api_ip_allowlist ?? []).join("\n"));
      onChange(next);
      toast.success(T.keys.ipSaved);
    },
    onError: (err) => {
      toast.error(fill(T.keys.ipError, { message: extractApiMessage(err) }));
    },
  });

  const revoke = useMutation<ApiKeyOut, ApiError, string>({
    mutationFn: (keyId) => revokeApiKey(merchantId, keyId, revokeKey.current),
    onSuccess: () => {
      setConfirming(null);
      toast.success(T.keys.revokedToast);
      void qc.invalidateQueries({ queryKey: qk.merchantKeys(merchantId) });
    },
    onError: (err) => {
      toast.error(fill(T.keys.revokeError, { message: extractApiMessage(err) }));
    },
  });

  const rows = keysQuery.data?.items ?? [];

  return (
    <section className="mb-6 rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
      <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold">
        <KeyRound size={16} />
        {T.keys.title}
      </h2>
      <p className="mb-3 text-xs text-[var(--text-secondary)]">{T.keys.hint}</p>

      {issued !== null && (
        // The only moment the key exists outside our encryption.
        <div
          role="status"
          translate="no"
          className="mb-4 rounded-lg border border-[var(--accent)] bg-[var(--bg-muted)] p-4"
        >
          <p className="text-sm font-semibold">{T.keys.secretTitle}</p>
          <p className="mt-1 text-xs text-[var(--text-secondary)]">{T.keys.secretBody}</p>

          <p className="mt-3 text-xs uppercase text-[var(--text-secondary)]">
            {T.keys.apiKeyLabel}
          </p>
          {issued.api_key === null ? (
            <p className="mt-1 text-xs text-[var(--danger-fg)]">{T.keys.secretReplayed}</p>
          ) : (
            <>
              <CopyValue value={issued.api_key} label={T.keys.copyApiKey} done={T.keys.copied} />
              <p className="mt-1 text-xs text-[var(--text-secondary)]">{T.keys.apiKeyHint}</p>
            </>
          )}

          <button
            type="button"
            onClick={() => {
              setIssued(null);
            }}
            className="rounded-btn mt-4 border px-3 py-1.5 text-xs font-semibold"
          >
            {T.keys.saved}
          </button>
        </div>
      )}

      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (create.isPending) return;
          createKey.current = `merchant-key-${crypto.randomUUID()}`;
          create.mutate();
        }}
      >
        <div className="min-w-0 flex-1">
          <label htmlFor={labelFieldId} className="text-xs uppercase text-[var(--text-secondary)]">
            {T.keys.labelLabel} <span className="normal-case">{T.keys.labelHint}</span>
          </label>
          <input
            id={labelFieldId}
            value={label}
            maxLength={64}
            onChange={(event) => {
              setLabel(event.target.value);
            }}
            placeholder={T.keys.labelPlaceholder}
            className="rounded-btn mt-1 w-full border px-3 py-2 text-sm"
          />
        </div>
        <button
          type="submit"
          disabled={create.isPending}
          className="rounded-btn border px-4 py-2 text-sm font-semibold disabled:opacity-60"
        >
          {create.isPending ? T.keys.createBusy : T.keys.create}
        </button>
      </form>

      <form
        className="mt-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (saveIps.isPending) return;
          saveIps.mutate();
        }}
      >
        <label htmlFor={ipFieldId} className="text-xs uppercase text-[var(--text-secondary)]">
          {T.keys.ipLabel} <span className="normal-case">{T.keys.ipHint}</span>
        </label>
        <textarea
          id={ipFieldId}
          rows={3}
          value={allowlist}
          onChange={(event) => {
            setAllowlist(event.target.value);
          }}
          className="rounded-btn mt-1 w-full border px-3 py-2 font-mono text-xs"
        />
        <button
          type="submit"
          disabled={saveIps.isPending}
          className="rounded-btn mt-2 border px-4 py-2 text-sm font-semibold disabled:opacity-60"
        >
          {T.keys.ipSave}
        </button>
      </form>

      {keysQuery.isError && (
        <p className="mt-4 text-xs text-[var(--danger-fg)]">
          {fill(T.keys.loadError, { message: extractApiMessage(keysQuery.error) })}
        </p>
      )}

      {!keysQuery.isLoading && !keysQuery.isError && rows.length === 0 && (
        <p className="mt-4 text-sm text-[var(--text-secondary)]">{T.keys.empty}</p>
      )}

      {rows.length > 0 && (
        <ul className="mt-4 divide-y border-t">
          {rows.map((key) => (
            <li key={key.key_id} className="flex flex-wrap items-start gap-x-4 gap-y-2 py-3">
              <div className="min-w-0 flex-1">
                {key.key_id.startsWith("ypk_") ? (
                  <p className="font-mono text-xs">{`${key.key_id.slice(0, 12)}…`}</p>
                ) : (
                  <CopyValue
                    value={key.key_id}
                    label={T.keys.copy}
                    done={T.keys.copied}
                    size="xs"
                  />
                )}
                <p className="mt-1 text-xs text-[var(--text-secondary)]">
                  {key.label || "—"} · {T.keys.lastUsed}:{" "}
                  {key.last_used_at === null ? T.keys.never : moment(key.last_used_at)}
                  {!key.key_id.startsWith("ypk_") && <> · {T.keys.legacyKey}</>}
                </p>
              </div>
              {key.revoked_at === null ? (
                <button
                  type="button"
                  onClick={() => {
                    revokeKey.current = `merchant-key-revoke-${crypto.randomUUID()}`;
                    setConfirming(key);
                  }}
                  className="rounded-btn border px-3 py-1.5 text-xs text-[var(--danger-fg)]"
                >
                  {T.keys.revoke}
                </button>
              ) : (
                <span className="text-xs text-[var(--text-secondary)]">
                  {fill(T.keys.revoked, { date: moment(key.revoked_at) })}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      {confirming !== null && (
        <ConfirmDialog
          title={T.keys.revokeConfirmTitle}
          tone="danger"
          confirmLabel={T.keys.revokeConfirm}
          cancelLabel={T.keys.cancel}
          busy={revoke.isPending}
          onCancel={() => {
            setConfirming(null);
          }}
          onConfirm={() => {
            revoke.mutate(confirming.key_id);
          }}
        >
          <p>{fill(T.keys.revokeConfirmBody, { key: `${confirming.key_id.slice(0, 12)}…` })}</p>
        </ConfirmDialog>
      )}
    </section>
  );
}
