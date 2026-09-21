"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import type { Webhook, WebhookWithSecret } from "@/lib/types";

import { CopyButton } from "@/components/CopyButton";
import { ApiError, api } from "@/lib/api";
import { formatMoment } from "@/lib/datetime";
import { pathFor } from "@/lib/locale-href";

/** A key per intent, held until the call succeeds — see `api.ts`. */
function newKey(): string {
  return `cab-${crypto.randomUUID()}`;
}

/**
 * Where a merchant points our deliveries, and how that endpoint is behaving.
 *
 * On Настройки rather than on «Журнал доставок», which is the delivery
 * **log**: the design separates "what I configured" from "what happened", and
 * a person arriving to change a URL is not the same person arriving to read a
 * 502. The sidebar used to call the log «Вебхуки», which put the two one word
 * apart and sent everybody hunting for the URL field on the wrong screen.
 */
export function WebhookCard({ locale }: { locale: string }) {
  const t = useTranslations("merchant.webhooks");

  const [hook, setHook] = useState<Webhook | null>(null);
  const [missing, setMissing] = useState(false);
  const [url, setUrl] = useState("");
  const [secret, setSecret] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [confirming, setConfirming] = useState<"rotate" | "disable" | null>(null);
  const [busy, setBusy] = useState(false);

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

  useEffect(() => {
    void loadHook();
  }, [loadHook]);

  /** Every write here: one key, one refresh, and the API's own words on a refusal. */
  const write = (run: () => Promise<WebhookWithSecret | Webhook>) => {
    setBusy(true);
    setError(null);
    setSent(false);
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
    <section className="border-border bg-card mt-6 rounded-xl border p-6">
      <h2 className="font-semibold">{t("title")}</h2>
      <p className="text-tx-mute mt-1.5 max-w-2xl text-sm leading-relaxed">{t("intro")}</p>

      {secret !== null && (
        <div role="status" className="border-primary bg-card-2 mt-6 rounded-xl border p-5">
          <p className="font-semibold">{t("secretOnceTitle")}</p>
          <p className="text-tx-mute mt-1.5 text-sm leading-relaxed">{t("secretOnceBody")}</p>
          <p className="mt-4 break-all font-mono text-sm">{secret}</p>
          <div className="mt-3">
            <CopyButton value={secret} label={t("copy")} done={t("copied")} />
          </div>
        </div>
      )}

      <div className="mt-5">
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
              className="border-border bg-card rounded-btn w-full border px-3.5 py-2.5 text-sm"
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

            {/* An auto-disabled hook used to be a red word and nothing else.
                The recovery path existed all along — `PUT /webhook` clears
                `disabled_at` and the streak, and does NOT rotate the secret —
                but the only way to find it was to re-type the URL you already
                had into the form above and press Save, which reads like a
                no-op. So a hook that fell over during an outage stayed off
                until somebody wrote to support. */}
            {hook.disabled_at !== null && (
              <div className="border-danger bg-card-2 mt-5 rounded-xl border p-4">
                <p className="text-tx-mute text-sm leading-relaxed">{t("disabledWhy")}</p>
                <button
                  type="button"
                  disabled={busy || url.trim() === ""}
                  onClick={() => {
                    const key = newKey();
                    // The URL as it stands in the field, which `loadHook`
                    // filled from the server: re-enabling is the same write
                    // as confirming the address, and the API says so.
                    write(() =>
                      api<WebhookWithSecret>("/webhook", {
                        method: "PUT",
                        body: { url },
                        idempotencyKey: key,
                      }),
                    );
                  }}
                  className="bg-primary text-primary-foreground rounded-btn mt-3 px-4 py-2 text-sm font-semibold disabled:opacity-60"
                >
                  {t("reenable")}
                </button>
              </div>
            )}

            <div className="mt-5 flex flex-wrap items-center gap-2">
              {confirming === null && (
                <>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      setBusy(true);
                      setError(null);
                      // Down the real path — same queue, same signature, same
                      // log — because that path is what is being tested.
                      void api<Webhook>("/webhook/test", { method: "POST" })
                        .then(() => {
                          setSent(true);
                        })
                        .catch((cause: unknown) => {
                          setError(cause instanceof ApiError ? cause.message : null);
                        })
                        .finally(() => {
                          setBusy(false);
                        });
                    }}
                    className="border-border rounded-btn border px-3 py-1.5 text-xs disabled:opacity-50"
                  >
                    {t("sendTest")}
                  </button>
                  {sent && (
                    <span role="status" className="text-primary-ink text-xs">
                      {t("testSent")}
                    </span>
                  )}
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
                    className="bg-danger rounded-btn px-3 py-1.5 text-xs font-semibold text-[hsl(var(--bg))] disabled:opacity-50"
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
      </div>

      <p className="text-tx-dim mt-5 text-xs">
        <a href={pathFor(locale, "/cabinet/webhooks")} className="underline underline-offset-4">
          {t("logLink")}
        </a>
      </p>
    </section>
  );
}
