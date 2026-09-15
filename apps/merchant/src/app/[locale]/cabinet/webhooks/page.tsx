"use client";

import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import type { DeliveriesPage, Webhook, WebhookDelivery, WebhookWithSecret } from "@/lib/types";

import { CopyButton } from "@/components/CopyButton";
import { ApiError, api } from "@/lib/api";
import { formatMoment } from "@/lib/datetime";

/** `status` → a key. Explicit and partial, like `labels.ts`: the worker's
 *  vocabulary is four words today and a fifth must show as itself. */
const DELIVERY_STATUS: Record<string, string> = {
  pending: "statusPending",
  in_progress: "statusInProgress",
  delivered: "statusDelivered",
  failed: "statusFailed",
};

/** A key per intent, held until the call succeeds — see `api.ts`. */
function newKey(): string {
  return `cab-${crypto.randomUUID()}`;
}

export default function WebhooksPage() {
  const t = useTranslations("merchant.webhooks");
  const { locale } = useParams<{ locale: string }>();

  const [hook, setHook] = useState<Webhook | null>(null);
  const [missing, setMissing] = useState(false);
  const [url, setUrl] = useState("");
  const [secret, setSecret] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<"rotate" | "disable" | null>(null);
  const [busy, setBusy] = useState(false);

  const [rows, setRows] = useState<WebhookDelivery[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const loadHook = useCallback(async () => {
    try {
      const current = await api<Webhook>("/webhook");
      setHook(current);
      setUrl(current.url);
      setMissing(false);
    } catch {
      // 404 until one is configured, which is the ordinary first visit.
      setMissing(true);
    }
  }, []);

  const loadDeliveries = useCallback(async (after: string | null) => {
    try {
      const query = after === null ? "" : `?cursor=${encodeURIComponent(after)}`;
      const page = await api<DeliveriesPage>(`/webhook/deliveries${query}`);
      setRows((previous) => (after === null ? page.items : [...(previous ?? []), ...page.items]));
      setCursor(page.next_cursor);
    } catch {
      setRows([]);
      setCursor(null);
    }
  }, []);

  useEffect(() => {
    void loadHook();
    void loadDeliveries(null);
  }, [loadHook, loadDeliveries]);

  /** Every write here: one key, one refresh, and the API's own words on a refusal. */
  const write = (run: () => Promise<WebhookWithSecret | Webhook>) => {
    setBusy(true);
    setError(null);
    void run()
      .then((result) => {
        if ("secret" in result && result.secret !== null) setSecret(result.secret);
        return loadHook();
      })
      .catch((cause: unknown) => {
        // The URL rules are the server's — https only, no private host — and
        // it states them precisely. Restating them here would be a second
        // copy that drifts from the one actually enforced.
        setError(cause instanceof ApiError ? cause.message : null);
      })
      .finally(() => {
        setConfirming(null);
        setBusy(false);
      });
  };

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
      <p className="text-tx-mute mt-2 max-w-2xl text-sm leading-relaxed">{t("intro")}</p>

      {secret !== null && (
        <div className="border-primary bg-card-2 mt-6 rounded-xl border p-5">
          <p className="font-semibold">{t("secretOnceTitle")}</p>
          <p className="text-tx-mute mt-1.5 text-sm leading-relaxed">{t("secretOnceBody")}</p>
          <p className="mt-4 break-all font-mono text-sm">{secret}</p>
          <div className="mt-3">
            <CopyButton value={secret} label={t("copy")} done={t("copied")} />
          </div>
        </div>
      )}

      <section className="border-border bg-card mt-6 rounded-xl border p-6">
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            const key = newKey();
            write(() =>
              api<WebhookWithSecret>("/webhook", {
                method: "PUT",
                body: { url },
                idempotencyKey: key,
              }),
            );
          }}
        >
          <div className="min-w-0 flex-1">
            <label htmlFor="hook-url" className="text-tx-mute mb-1.5 block text-sm">
              {t("urlLabel")}
            </label>
            <input
              id="hook-url"
              type="url"
              required
              value={url}
              placeholder="https://"
              onChange={(event) => {
                setUrl(event.target.value);
              }}
              className="border-border bg-card rounded-btn w-full border px-3.5 py-2.5 text-sm outline-none"
            />
          </div>
          <button
            type="submit"
            disabled={busy}
            className="bg-primary text-primary-foreground rounded-btn px-4 py-2.5 text-sm font-semibold disabled:opacity-60"
          >
            {t("save")}
          </button>
          <p className="text-tx-dim w-full text-xs">{t("urlHint")}</p>
        </form>

        {error !== null && (
          <p role="alert" className="text-danger mt-3 text-sm leading-relaxed">
            {error}
          </p>
        )}

        {missing && <p className="text-tx-dim mt-5 text-sm">{t("notConfigured")}</p>}

        {hook !== null && (
          <div className="border-border mt-5 border-t pt-5">
            <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
              <div>
                <dt className="text-tx-mute text-sm">{t("health")}</dt>
                <dd className={`mt-0.5 font-medium ${hook.disabled_at ? "text-danger" : ""}`}>
                  {hook.disabled_at ? t("disabled") : t("active")}
                </dd>
              </div>
              <div>
                <dt className="text-tx-mute text-sm">{t("failureStreak")}</dt>
                <dd className="mt-0.5 font-mono font-medium">{hook.failure_streak}</dd>
              </div>
              <div>
                <dt className="text-tx-mute text-sm">{t("lastSuccess")}</dt>
                <dd className="mt-0.5">
                  {hook.last_success_at === null ? (
                    <span className="text-tx-dim">{t("never")}</span>
                  ) : (
                    formatMoment(hook.last_success_at, locale)
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-tx-mute text-sm">{t("lastFailure")}</dt>
                <dd className="mt-0.5">
                  {hook.last_failure_at === null ? (
                    <span className="text-tx-dim">{t("never")}</span>
                  ) : (
                    formatMoment(hook.last_failure_at, locale)
                  )}
                </dd>
              </div>
            </dl>

            <div className="mt-5 flex flex-wrap items-center gap-2">
              {confirming === null && (
                <>
                  <button
                    type="button"
                    onClick={() => {
                      setConfirming("rotate");
                    }}
                    className="border-border rounded-btn border px-3 py-1.5 text-xs"
                  >
                    {t("rotate")}
                  </button>
                  {hook.disabled_at === null && (
                    <button
                      type="button"
                      onClick={() => {
                        setConfirming("disable");
                      }}
                      className="border-border text-danger rounded-btn border px-3 py-1.5 text-xs"
                    >
                      {t("disable")}
                    </button>
                  )}
                </>
              )}
              {confirming !== null && (
                <>
                  <p className="text-tx-mute w-full text-xs">
                    {confirming === "rotate" ? t("rotateConfirm") : t("disableConfirm")}
                  </p>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      const key = newKey();
                      write(() =>
                        confirming === "rotate"
                          ? api<WebhookWithSecret>("/webhook/rotate-secret", {
                              method: "POST",
                              idempotencyKey: key,
                            })
                          : api<Webhook>("/webhook", { method: "DELETE", idempotencyKey: key }),
                      );
                    }}
                    className="bg-danger rounded-btn px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
                  >
                    {confirming === "rotate" ? t("rotateYes") : t("disableYes")}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setConfirming(null);
                    }}
                    className="border-border text-tx-mute rounded-btn border px-3 py-1.5 text-xs"
                  >
                    {t("cancel")}
                  </button>
                </>
              )}
            </div>
          </div>
        )}
      </section>

      <section className="border-border bg-card mt-6 rounded-xl border p-6">
        <h2 className="font-semibold">{t("logTitle")}</h2>

        {rows !== null && rows.length === 0 && (
          <p className="text-tx-dim mt-3 text-sm">{t("logEmpty")}</p>
        )}

        {rows !== null && rows.length > 0 && (
          <ul className="border-border divide-border mt-4 divide-y border-t">
            {rows.map((row) => {
              const statusKey = DELIVERY_STATUS[row.status];
              const expanded = open === row.id;
              return (
                <li key={row.id} className="py-3.5">
                  <button
                    type="button"
                    aria-expanded={expanded}
                    onClick={() => {
                      setOpen(expanded ? null : row.id);
                    }}
                    className="flex w-full flex-wrap items-baseline gap-x-4 gap-y-1 text-left text-sm"
                  >
                    <span className="min-w-0 flex-1 font-mono text-xs">{row.event_type}</span>
                    <span className={row.status === "failed" ? "text-danger" : "text-tx-mute"}>
                      {statusKey === undefined ? row.status : t(statusKey)}
                    </span>
                    <span className="font-mono text-xs">{row.response_code ?? "—"}</span>
                    <span className="text-tx-dim font-mono text-xs">×{row.attempts_count}</span>
                    <span className="text-tx-dim whitespace-nowrap text-xs">
                      {formatMoment(row.created_at, locale)}
                    </span>
                  </button>

                  {expanded && (
                    <div className="mt-3 space-y-3 text-xs">
                      <p className="text-tx-dim break-all font-mono">{row.url}</p>
                      <div>
                        <p className="text-tx-mute mb-1">{t("sent")}</p>
                        <pre className="bg-card-2 rounded-btn max-h-64 overflow-auto p-3 font-mono">
                          {JSON.stringify(row.payload, null, 2)}
                        </pre>
                      </div>
                      {row.response_body !== null && (
                        <div>
                          <p className="text-tx-mute mb-1">{t("received")}</p>
                          <pre className="bg-card-2 rounded-btn max-h-40 overflow-auto p-3 font-mono">
                            {row.response_body}
                          </pre>
                        </div>
                      )}
                      {row.last_error !== null && (
                        <p className="text-danger break-words">
                          {t("error")}: {row.last_error}
                        </p>
                      )}
                      {row.status === "pending" && (
                        <p className="text-tx-dim">
                          {t("nextAttempt")}: {formatMoment(row.next_attempt_at, locale)}
                        </p>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        {cursor !== null && (
          <button
            type="button"
            onClick={() => {
              void loadDeliveries(cursor);
            }}
            className="border-border rounded-btn mt-5 border px-4 py-2 text-sm font-semibold"
          >
            {t("loadMore")}
          </button>
        )}
      </section>
    </div>
  );
}
