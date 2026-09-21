import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useId, useRef, useState } from "react";

import {
  T,
  createApiKey,
  fetchApiKeys,
  fill,
  revokeApiKey,
  type ApiKeyCreatedOut,
  type ApiKeyOut,
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
 * Revoked keys stay in the list, as the API intends: "which credential was
 * live when this broke" is a question that only an unfiltered list answers.
 */
export function MerchantKeysCard({ merchantId }: { merchantId: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const labelFieldId = useId();
  const ipFieldId = useId();

  const [label, setLabel] = useState("");
  const [allowlist, setAllowlist] = useState("");
  const [issued, setIssued] = useState<ApiKeyCreatedOut | null>(null);
  const [confirming, setConfirming] = useState<ApiKeyOut | null>(null);
  const createKey = useRef("");
  const revokeKey = useRef("");

  const keysQuery = useQuery({
    queryKey: qk.merchantKeys(merchantId),
    queryFn: () => fetchApiKeys(merchantId),
  });

  const create = useMutation<ApiKeyCreatedOut, ApiError>({
    mutationFn: () => {
      // Blank lines and stray spaces are the ordinary result of pasting a
      // list; the server refuses an unparseable entry, so what is sent must
      // already be free of the ones nobody meant to type.
      const ips = allowlist
        .split("\n")
        .map((line) => line.trim())
        .filter((line) => line !== "");
      return createApiKey(
        merchantId,
        { label, ip_allowlist: ips.length > 0 ? ips : null },
        createKey.current,
      );
    },
    onSuccess: (key) => {
      setIssued(key);
      setLabel("");
      setAllowlist("");
      void qc.invalidateQueries({ queryKey: qk.merchantKeys(merchantId) });
    },
    onError: (err) => {
      toast.error(fill(T.keys.createError, { message: extractApiMessage(err) }));
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
        // The only moment the secret exists outside our encryption. Both
        // halves are labelled and each says its prefix, because three of our
        // secrets begin `ypm` and a reader cannot tell them apart by shape —
        // the confusion that cost one integration a day.
        <div
          role="status"
          translate="no"
          className="mb-4 rounded-lg border border-[var(--accent)] bg-[var(--bg-muted)] p-4"
        >
          <p className="text-sm font-semibold">{T.keys.secretTitle}</p>
          <p className="mt-1 text-xs text-[var(--text-secondary)]">{T.keys.secretBody}</p>

          <p className="mt-3 text-xs uppercase text-[var(--text-secondary)]">{T.keys.keyIdLabel}</p>
          <CopyValue value={issued.key_id} label={T.keys.copyKeyId} done={T.keys.copied} />
          <p className="mt-1 text-xs text-[var(--text-secondary)]">{T.keys.keyIdHint}</p>

          <p className="mt-4 text-xs uppercase text-[var(--text-secondary)]">
            {T.keys.secretLabel}
          </p>
          {issued.secret === null ? (
            <p className="mt-1 text-xs text-[var(--danger-fg)]">{T.keys.secretReplayed}</p>
          ) : (
            <>
              <CopyValue value={issued.secret} label={T.keys.copySecret} done={T.keys.copied} />
              <p className="mt-1 text-xs text-[var(--text-secondary)]">{T.keys.secretHint}</p>
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
        className="grid grid-cols-1 gap-3 md:grid-cols-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (create.isPending) return;
          createKey.current = `merchant-key-${crypto.randomUUID()}`;
          create.mutate();
        }}
      >
        <div>
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
        <div className="md:col-span-2">
          <label htmlFor={ipFieldId} className="text-xs uppercase text-[var(--text-secondary)]">
            {T.keys.ipLabel} <span className="normal-case">{T.keys.ipHint}</span>
          </label>
          <textarea
            id={ipFieldId}
            rows={2}
            value={allowlist}
            onChange={(event) => {
              setAllowlist(event.target.value);
            }}
            className="rounded-btn mt-1 w-full border px-3 py-2 font-mono text-xs"
          />
        </div>
        <div className="md:col-span-3">
          <button
            type="submit"
            disabled={create.isPending}
            className="rounded-btn border px-4 py-2 text-sm font-semibold disabled:opacity-60"
          >
            {create.isPending ? T.keys.createBusy : T.keys.create}
          </button>
        </div>
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
                <CopyValue value={key.key_id} label={T.keys.copy} done={T.keys.copied} size="xs" />
                <p className="mt-1 text-xs text-[var(--text-secondary)]">
                  {key.label || "—"} · {T.keys.lastUsed}:{" "}
                  {key.last_used_at === null ? T.keys.never : moment(key.last_used_at)}
                </p>
                <p className="mt-0.5 font-mono text-xs text-[var(--text-secondary)]">
                  {key.ip_allowlist === null ? T.keys.noFilter : key.ip_allowlist.join(", ")}
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
          <p>{fill(T.keys.revokeConfirmBody, { key: confirming.key_id })}</p>
        </ConfirmDialog>
      )}
    </section>
  );
}
