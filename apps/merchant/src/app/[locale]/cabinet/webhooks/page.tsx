"use client";

import { ChevronDown, Webhook } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import type { DeliveriesPage, WebhookDelivery } from "@/lib/types";

import { EmptyState } from "@/components/EmptyState";
import { ListSkeleton } from "@/components/ListSkeleton";
import { LoadError } from "@/components/LoadError";
import { PageHeading } from "@/components/PageHeading";
import { api } from "@/lib/api";
import { formatMoment } from "@/lib/datetime";
import { pathFor } from "@/lib/locale-href";

/** `status` → a key. Explicit and partial, like `labels.ts`: the worker's
 *  vocabulary is four words today and a fifth must show as itself. */
const DELIVERY_STATUS: Record<string, string> = {
  pending: "statusPending",
  in_progress: "statusInProgress",
  delivered: "statusDelivered",
  failed: "statusFailed",
};

const TONE: Record<string, string> = {
  delivered: "text-primary-ink bg-primary/10",
  failed: "text-danger bg-danger/10",
  in_progress: "text-blue bg-blue/10",
  pending: "text-gold bg-gold/10",
};

/**
 * The delivery log: what we sent, where it went, what came back.
 *
 * Configuration lives on Настройки — the design separates "what I set up"
 * from "what happened", and a person arriving to read a 502 is not the person
 * arriving to change a URL. The intro links there rather than merely naming
 * it: this is the screen somebody opens while their integration is broken.
 */
export default function WebhookLog() {
  const t = useTranslations("merchant.webhooks");
  const { locale } = useParams<{ locale: string }>();

  const [rows, setRows] = useState<WebhookDelivery[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [cursor, setCursor] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async (after: string | null) => {
    try {
      const query = after === null ? "" : `?cursor=${encodeURIComponent(after)}`;
      const page = await api<DeliveriesPage>(`/webhook/deliveries${query}`);
      setFailed(false);
      setRows((previous) => (after === null ? page.items : [...(previous ?? []), ...page.items]));
      setCursor(page.next_cursor);
    } catch {
      // An error, not «no deliveries yet».
      if (after === null) setFailed(true);
    }
  }, []);

  useEffect(() => {
    void load(null);
  }, [load]);

  return (
    <div>
      <PageHeading icon={Webhook} title={t("logTitle")} />
      <p className="text-tx-mute mt-2 max-w-2xl text-sm leading-relaxed">
        {t("logIntro")}{" "}
        {/* The sentence used to END "...live in Настройки" as flat prose, on
            the one screen somebody reaches while their integration is broken.
            Naming a destination without linking to it makes the reader hunt a
            sidebar; the two screens are one click apart. */}
        <Link href={pathFor(locale, "/cabinet/settings")} className="underline underline-offset-4">
          {t("logConfigLink")}
        </Link>
      </p>

      {rows === null && !failed && <ListSkeleton className="mt-5" />}
      {rows === null && failed && (
        <LoadError
          onRetry={() => {
            setFailed(false);
            void load(null);
          }}
        />
      )}

      {rows !== null && rows.length === 0 && (
        <EmptyState icon={Webhook} title={t("logEmpty")} hint={t("logEmptyHint")} />
      )}

      {rows !== null && rows.length > 0 && (
        // Fixed columns with a header row: with free-flowing cells every status
        // chip sat at a different x, and «200 ×1» meant nothing without labels.
        <div className="border-border bg-card mt-5 overflow-hidden rounded-xl border">
          <div className="text-tx-dim border-border hidden grid-cols-[minmax(0,1fr)_9rem_5rem_5rem_9rem_1.25rem] gap-x-4 border-b px-4 py-3 text-xs font-medium sm:grid">
            <span>{t("colEvent")}</span>
            <span>{t("colStatus")}</span>
            <span className="text-right">{t("colCode")}</span>
            <span className="text-right">{t("colAttempts")}</span>
            <span className="text-right">{t("colWhen")}</span>
            <span />
          </div>
          <ul className="divide-border divide-y">
            {rows.map((row) => {
              const statusKey = DELIVERY_STATUS[row.status];
              const expanded = open === row.id;
              const ok = row.response_code !== null && row.response_code < 300;
              return (
                <li key={row.id}>
                  <button
                    type="button"
                    aria-expanded={expanded}
                    onClick={() => {
                      setOpen(expanded ? null : row.id);
                    }}
                    className="hover:bg-card-2/60 grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1.5 px-4 py-3 text-left text-sm transition-colors sm:grid-cols-[minmax(0,1fr)_9rem_5rem_5rem_9rem_1.25rem]"
                  >
                    <span className="min-w-0 truncate font-mono text-xs">{row.event_type}</span>
                    <span>
                      <span
                        className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${
                          TONE[row.status] ?? "text-tx-mute bg-tx-mute/10"
                        }`}
                      >
                        {statusKey === undefined ? row.status : t(statusKey)}
                      </span>
                    </span>
                    {/* A phone gets the three numbers on one line under the event. */}
                    <span className="text-tx-dim col-span-2 text-xs sm:hidden">
                      <span className={ok || row.response_code === null ? "" : "text-danger"}>
                        {row.response_code ?? "—"}
                      </span>
                      {` · ×${String(row.attempts_count)} · ${formatMoment(row.created_at, locale)}`}
                    </span>
                    <span
                      className={`hidden text-right font-mono text-xs sm:block ${
                        row.response_code === null ? "text-tx-dim" : ok ? "" : "text-danger"
                      }`}
                    >
                      {row.response_code ?? "—"}
                    </span>
                    <span className="text-tx-dim hidden text-right font-mono text-xs sm:block">
                      ×{row.attempts_count}
                    </span>
                    <span className="text-tx-dim hidden whitespace-nowrap text-right text-xs sm:block">
                      {formatMoment(row.created_at, locale)}
                    </span>
                    <ChevronDown
                      aria-hidden
                      size={15}
                      className={`text-tx-dim hidden transition-transform sm:block ${
                        expanded ? "rotate-180" : ""
                      }`}
                    />
                  </button>

                  {expanded && (
                    <div className="space-y-3 px-4 pb-4 text-xs">
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
        </div>
      )}

      {cursor !== null && (
        <button
          type="button"
          onClick={() => {
            void load(cursor);
          }}
          className="border-border rounded-btn mt-5 border px-4 py-2 text-sm font-semibold"
        >
          {t("loadMore")}
        </button>
      )}
    </div>
  );
}
