import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Webhook } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import {
  T,
  disableWebhook,
  fetchWebhook,
  fetchWebhookDeliveries,
  fill,
  rotateWebhookSecret,
  setWebhook,
  type WebhookDeliveryOut,
  type WebhookOut,
  type WebhookSecretOut,
} from "./api";
import { CopyValue } from "./CopyValue";

import type { ApiError } from "@/lib/api";

import { Badge } from "@/components/Badge";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useToast } from "@/components/Toast";
import { ApiError as ApiErrorClass } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";
import { qk } from "@/lib/queryKeys";

function moment(iso: string): string {
  return new Date(iso).toLocaleString("ru");
}

/**
 * Where a merchant's events go, and whether they are arriving.
 *
 * Four endpoints shipped with the B2B milestone and had no button: set the
 * URL, read the health, rotate the secret, disable. The health is the half
 * that matters for support — `failure_streak`, the two timestamps and
 * `disabled_at` are the only way to answer "my webhooks stopped" without
 * asking the merchant to read their own cabinet back to you.
 *
 * `404` is the ordinary answer for a merchant who never configured one, so
 * it renders as a sentence rather than an error.
 */
export function MerchantWebhookCard({ merchantId }: { merchantId: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const urlFieldId = useId();

  const [url, setUrl] = useState("");
  const [touched, setTouched] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const [secretUnchanged, setSecretUnchanged] = useState(false);
  const [confirming, setConfirming] = useState<"rotate" | "disable" | null>(null);
  // The log is opt-in, and stays that way: it carries the request bodies we
  // sent, so it is not something to put in front of an operator who only
  // came to change a URL.
  const [logOpen, setLogOpen] = useState(false);
  const [cursor, setCursor] = useState<string | null>(null);
  const [rows, setRows] = useState<WebhookDeliveryOut[]>([]);
  const [openRow, setOpenRow] = useState<string | null>(null);
  const writeKey = useRef("");

  const hookQuery = useQuery({
    queryKey: qk.merchantWebhook(merchantId),
    queryFn: () => fetchWebhook(merchantId),
    // A merchant with no webhook is the ordinary first state, not a failure
    // to retry — `fetchWebhook` answers 404 and React Query would otherwise
    // spend three attempts discovering that again on every mount.
    retry: (count, error) => !(error instanceof ApiErrorClass && error.status === 404) && count < 2,
  });

  const hook = hookQuery.data ?? null;
  const missing = hookQuery.isError && (hookQuery.error as ApiError).status === 404;
  // The field follows the server until the operator types, so it is never
  // stale and never fights them mid-edit.
  const value = touched ? url : (hook?.url ?? "");

  const afterWrite = (result: WebhookSecretOut | WebhookOut) => {
    if ("secret" in result) {
      if (result.secret !== null) setSecret(result.secret);
      else setSecretUnchanged(true);
    }
    setTouched(false);
    void qc.invalidateQueries({ queryKey: qk.merchantWebhook(merchantId) });
  };

  const save = useMutation<WebhookSecretOut, ApiError, string>({
    mutationFn: (next) => setWebhook(merchantId, next, writeKey.current),
    onSuccess: (result) => {
      afterWrite(result);
      toast.success(T.hook.savedToast);
    },
    // The server owns the URL rules — https only, no private host — and
    // states them precisely. Restating them here would be a second copy that
    // drifts from the one actually enforced.
    onError: (err) => {
      toast.error(fill(T.hook.saveError, { message: extractApiMessage(err) }));
    },
  });

  const rotate = useMutation<WebhookSecretOut, ApiError>({
    mutationFn: () => rotateWebhookSecret(merchantId, writeKey.current),
    onSuccess: (result) => {
      setConfirming(null);
      afterWrite(result);
      toast.success(T.hook.rotatedToast);
    },
    onError: (err) => {
      toast.error(fill(T.hook.rotateError, { message: extractApiMessage(err) }));
    },
  });

  const disable = useMutation<WebhookOut, ApiError>({
    mutationFn: () => disableWebhook(merchantId, writeKey.current),
    onSuccess: (result) => {
      setConfirming(null);
      afterWrite(result);
      toast.success(T.hook.disabledToast);
    },
    onError: (err) => {
      toast.error(fill(T.hook.disableError, { message: extractApiMessage(err) }));
    },
  });

  const busy = save.isPending || rotate.isPending || disable.isPending;

  const logQuery = useQuery({
    queryKey: qk.merchantDeliveries(merchantId, cursor),
    queryFn: () => fetchWebhookDeliveries(merchantId, cursor),
    enabled: logOpen,
  });

  const nextCursor = logQuery.data?.next_cursor ?? null;

  // Pages append rather than replace: an incident is read by walking back
  // through the retries, and a list that jumped to page two loses the row
  // the operator was comparing against.
  useEffect(() => {
    const page = logQuery.data;
    if (page === undefined) return;
    setRows((previous) => {
      const seen = new Set(previous.map((row) => row.id));
      return [...previous, ...page.items.filter((row) => !seen.has(row.id))];
    });
  }, [logQuery.data]);

  return (
    <section className="mb-6 rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
      <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold">
        <Webhook size={16} />
        {T.hook.title}
      </h2>
      <p className="mb-3 text-xs text-[var(--text-secondary)]">{T.hook.hint}</p>

      {(secret !== null || secretUnchanged) && (
        <div
          role="status"
          translate="no"
          className="mb-4 rounded-lg border border-[var(--accent)] bg-[var(--bg-muted)] p-4"
        >
          <p className="text-sm font-semibold">{T.hook.secretTitle}</p>
          {secret === null ? (
            <p className="mt-1 text-xs text-[var(--text-secondary)]">{T.hook.secretNull}</p>
          ) : (
            <>
              <p className="mt-1 text-xs text-[var(--text-secondary)]">{T.hook.secretBody}</p>
              <div className="mt-3">
                <CopyValue value={secret} label={T.hook.copy} done={T.hook.copied} />
              </div>
            </>
          )}
          <button
            type="button"
            onClick={() => {
              setSecret(null);
              setSecretUnchanged(false);
            }}
            className="rounded-btn mt-4 border px-3 py-1.5 text-xs font-semibold"
          >
            {T.hook.saved}
          </button>
        </div>
      )}

      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (busy) return;
          writeKey.current = `merchant-hook-${crypto.randomUUID()}`;
          save.mutate(value);
        }}
      >
        <div className="min-w-0 flex-1">
          <label htmlFor={urlFieldId} className="text-xs uppercase text-[var(--text-secondary)]">
            {T.hook.urlLabel} <span className="normal-case">{T.hook.urlHint}</span>
          </label>
          <input
            id={urlFieldId}
            type="url"
            required
            value={value}
            placeholder="https://"
            onChange={(event) => {
              setTouched(true);
              setUrl(event.target.value);
            }}
            className="rounded-btn mt-1 w-full border px-3 py-2 text-sm"
          />
        </div>
        <button
          type="submit"
          disabled={busy}
          className="rounded-btn border px-4 py-2 text-sm font-semibold disabled:opacity-60"
        >
          {save.isPending ? T.hook.saveBusy : T.hook.save}
        </button>
      </form>
      <p className="mt-2 text-xs text-[var(--text-secondary)]">{T.hook.reenableNote}</p>

      {missing && <p className="mt-4 text-sm text-[var(--text-secondary)]">{T.hook.none}</p>}
      {hookQuery.isError && !missing && (
        <p className="mt-4 text-xs text-[var(--danger-fg)]">
          {fill(T.hook.loadError, { message: extractApiMessage(hookQuery.error) })}
        </p>
      )}

      {hook !== null && (
        <>
          <dl className="mt-4 grid gap-x-8 gap-y-3 border-t pt-4 sm:grid-cols-2">
            <div>
              <dt className="text-xs text-[var(--text-secondary)]">{T.hook.health}</dt>
              <dd className="mt-0.5 text-sm font-medium">
                {hook.disabled_at === null ? (
                  <Badge tone="bg-[var(--success-soft)] text-[var(--success-fg)]" dot>
                    {T.hook.active}
                  </Badge>
                ) : (
                  <Badge tone="bg-[var(--danger-soft)] text-[var(--danger-fg)]" dot>
                    {fill(T.hook.disabled, { date: moment(hook.disabled_at) })}
                  </Badge>
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--text-secondary)]">{T.hook.streak}</dt>
              <dd className="mt-0.5 font-mono text-sm font-medium">{hook.failure_streak}</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--text-secondary)]">{T.hook.lastSuccess}</dt>
              <dd className="mt-0.5 text-sm">
                {hook.last_success_at === null ? T.hook.never : moment(hook.last_success_at)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--text-secondary)]">{T.hook.lastFailure}</dt>
              <dd className="mt-0.5 text-sm">
                {hook.last_failure_at === null ? T.hook.never : moment(hook.last_failure_at)}
              </dd>
            </div>
          </dl>

          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                writeKey.current = `merchant-hook-rotate-${crypto.randomUUID()}`;
                setConfirming("rotate");
              }}
              className="rounded-btn border px-3 py-1.5 text-xs disabled:opacity-50"
            >
              {T.hook.rotate}
            </button>
            {hook.disabled_at === null && (
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  writeKey.current = `merchant-hook-disable-${crypto.randomUUID()}`;
                  setConfirming("disable");
                }}
                className="rounded-btn border px-3 py-1.5 text-xs text-[var(--danger-fg)] disabled:opacity-50"
              >
                {T.hook.disable}
              </button>
            )}
          </div>
        </>
      )}

      {hook !== null && (
        <div className="mt-6 border-t pt-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold">{T.log.title}</h3>
              <p className="text-xs text-[var(--text-secondary)]">{T.log.hint}</p>
            </div>
            <button
              type="button"
              onClick={() => {
                setLogOpen((open) => !open);
              }}
              className="rounded-btn border px-3 py-1.5 text-xs"
            >
              {logOpen ? T.log.hide : T.log.show}
            </button>
          </div>

          {logOpen && logQuery.isError && (
            <p className="mt-3 text-xs text-[var(--danger-fg)]">
              {fill(T.log.loadError, { message: extractApiMessage(logQuery.error as ApiError) })}
            </p>
          )}

          {logOpen && !logQuery.isLoading && !logQuery.isError && rows.length === 0 && (
            <p className="mt-3 text-sm text-[var(--text-secondary)]">{T.log.empty}</p>
          )}

          {logOpen && rows.length > 0 && (
            <ul className="mt-3 divide-y border-t">
              {rows.map((row) => (
                <li key={row.id} className="py-2.5">
                  <button
                    type="button"
                    aria-expanded={openRow === row.id}
                    onClick={() => {
                      setOpenRow(openRow === row.id ? null : row.id);
                    }}
                    className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 text-left text-xs"
                  >
                    <span className="min-w-0 flex-1 truncate font-mono">{row.event_type}</span>
                    <span className="font-mono">{row.status}</span>
                    <span className="font-mono">{row.response_code ?? "—"}</span>
                    <span className="text-[var(--text-secondary)]">
                      {row.attempts_count} {T.log.attempts}
                    </span>
                    <span className="whitespace-nowrap text-[var(--text-secondary)]">
                      {moment(row.created_at)}
                    </span>
                  </button>
                  {openRow === row.id && (
                    <div className="mt-2 space-y-2 text-xs">
                      <p className="break-all font-mono text-[var(--text-secondary)]">{row.url}</p>
                      <p className="text-[var(--text-secondary)]">{T.log.sent}</p>
                      <pre className="max-h-48 overflow-auto rounded bg-[var(--bg-muted)] p-2 font-mono">
                        {JSON.stringify(row.payload, null, 2)}
                      </pre>
                      {row.response_body !== null && (
                        <>
                          <p className="text-[var(--text-secondary)]">{T.log.received}</p>
                          <pre className="max-h-32 overflow-auto rounded bg-[var(--bg-muted)] p-2 font-mono">
                            {row.response_body}
                          </pre>
                        </>
                      )}
                      {row.last_error !== null && (
                        <p className="break-words text-[var(--danger-fg)]">
                          {T.log.error}: {row.last_error}
                        </p>
                      )}
                      {row.status === "pending" && (
                        <p className="text-[var(--text-secondary)]">
                          {T.log.nextAttempt}: {moment(row.next_attempt_at)}
                        </p>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}

          {logOpen && nextCursor !== null && (
            <button
              type="button"
              onClick={() => {
                setCursor(nextCursor);
              }}
              className="rounded-btn mt-3 border px-3 py-1.5 text-xs"
            >
              {T.log.loadMore}
            </button>
          )}
        </div>
      )}

      {confirming !== null && (
        <ConfirmDialog
          title={confirming === "rotate" ? T.hook.rotateConfirmTitle : T.hook.disableConfirmTitle}
          tone="danger"
          confirmLabel={confirming === "rotate" ? T.hook.rotateConfirm : T.hook.disableConfirm}
          cancelLabel={T.hook.cancel}
          busy={busy}
          onCancel={() => {
            setConfirming(null);
          }}
          onConfirm={() => {
            if (confirming === "rotate") rotate.mutate();
            else disable.mutate();
          }}
        >
          <p>{confirming === "rotate" ? T.hook.rotateConfirmBody : T.hook.disableConfirmBody}</p>
        </ConfirmDialog>
      )}
    </section>
  );
}
