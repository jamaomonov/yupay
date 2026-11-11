"use client";

import { CircleCheck } from "lucide-react";
import { useTranslations } from "next-intl";

import type { UsdtFlow } from "@/lib/useUsdtDeposit";

import { useCabinet } from "@/components/CabinetContext";
import { UsdtDetails } from "@/components/UsdtDetails";
import { UsdtNetworkPicker } from "@/components/UsdtNetworkPicker";
import { formatMoment } from "@/lib/datetime";
import {
  checkAmount,
  explorerTxLink,
  formatUsdt,
  networkLabel,
  sanitizeAmount,
  shortHash,
  USDT_PRESETS,
} from "@/lib/usdt";

const BUTTON =
  "bg-primary text-primary-foreground rounded-btn mt-4 inline-flex px-4 py-2 text-sm font-semibold";

interface UsdtTopUpProps {
  flow: UsdtFlow;
  locale: string;
  supportHref: string;
  /** Back to the method picker. */
  onBack: () => void;
  /** "Top up again": the page also drops the picked method. */
  onAgain: () => void;
}

interface AmountFormProps {
  flow: UsdtFlow;
  locale: string;
  onBack: () => void;
}

/** The amount in USDT: typed or picked from the presets, checked against the bounds. */
function AmountForm({ flow, locale, onBack }: AmountFormProps) {
  const t = useTranslations("merchant.topUpUsdt");
  const { usdt } = useCabinet();
  const min = usdt?.min_amount ?? null;
  const max = usdt?.max_amount ?? null;
  const check = checkAmount(flow.amount, min, max);
  const grouped = new Intl.NumberFormat(locale);

  return (
    <form
      className="border-border bg-card mt-5 max-w-md rounded-xl border p-6"
      onSubmit={(event) => {
        event.preventDefault();
        void flow.submit();
      }}
    >
      <button
        type="button"
        onClick={onBack}
        className="text-tx-mute mb-3 text-sm underline-offset-4 hover:underline"
      >
        ← {t("changeMethod")}
      </button>
      <label className="text-tx-dim block text-xs" htmlFor="usdt-amount">
        {t("amountLabel")}
      </label>
      <div className="relative mt-1.5">
        <input
          id="usdt-amount"
          inputMode="decimal"
          autoComplete="off"
          value={flow.amount}
          onChange={(event) => {
            flow.setAmount(sanitizeAmount(event.target.value));
          }}
          className="border-border bg-card-2 rounded-btn block w-full border py-2 pl-3 pr-16 font-mono text-lg"
        />
        <span className="text-tx-dim pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm font-semibold">
          USDT
        </span>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {USDT_PRESETS.map((preset) => (
          <button
            key={preset}
            type="button"
            onClick={() => {
              flow.setAmount(String(preset));
            }}
            className="border-border hover:border-primary rounded-btn border px-3 py-1.5 font-mono text-sm tabular-nums transition-colors"
          >
            {grouped.format(preset)}
          </button>
        ))}
      </div>
      {min !== null && max !== null && (
        <p
          className={`mt-3 text-sm ${check === "low" || check === "high" ? "text-red-500" : "text-tx-mute"}`}
        >
          {t("range", { min: formatUsdt(min, locale), max: formatUsdt(max, locale) })}
        </p>
      )}
      {flow.offer !== null && (
        <div
          role="alert"
          className="mt-4 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm leading-relaxed"
        >
          <p className="font-semibold">
            {t("takenTitle", { asked: formatUsdt(flow.offer.asked, locale) })}
          </p>
          <p className="text-tx-mute mt-1">
            {t("takenOffer", { suggested: flow.offer.suggested })}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={flow.busy}
              onClick={() => {
                void flow.acceptOffer();
              }}
              className="bg-primary text-primary-foreground rounded-btn px-4 py-2 text-sm font-semibold disabled:opacity-50"
            >
              {t("takenAccept", { suggested: flow.offer.suggested })}
            </button>
            <button
              type="button"
              onClick={() => {
                flow.declineOffer();
                document.getElementById("usdt-amount")?.focus();
              }}
              className="border-border rounded-btn border px-4 py-2 text-sm font-semibold"
            >
              {t("takenBack")}
            </button>
          </div>
        </div>
      )}
      {flow.error !== null && (
        <p role="alert" className="mt-3 text-sm text-red-500">
          {flow.error}
        </p>
      )}
      {flow.offer === null && (
        <button
          type="submit"
          disabled={flow.busy || check !== "ok"}
          className="bg-primary text-primary-foreground rounded-btn mt-4 px-4 py-2 text-sm font-semibold disabled:opacity-50"
        >
          {t("continue")}
        </button>
      )}
    </form>
  );
}

/** The USDT top-up: amount, then the chain, then where and how much to send, then the outcome. */
export function UsdtTopUp({ flow, locale, supportHref, onBack, onAgain }: UsdtTopUpProps) {
  const t = useTranslations("merchant.topUpUsdt");
  const { deposit, phase } = flow;

  const again = (
    <button
      type="button"
      onClick={() => {
        flow.reset();
        onAgain();
      }}
      className={BUTTON}
    >
      {t("again")}
    </button>
  );

  if (phase === "amount" || phase === "cancelled" || deposit === null)
    return flow.choosing ? (
      <UsdtNetworkPicker flow={flow} locale={locale} />
    ) : (
      <AmountForm flow={flow} locale={locale} onBack={onBack} />
    );

  if (phase === "details")
    return (
      <UsdtDetails
        deposit={deposit}
        nowMs={flow.nowMs}
        locale={locale}
        busy={flow.busy}
        error={flow.error}
        onCancel={() => {
          void flow.cancel();
        }}
      />
    );

  if (phase === "paid")
    return (
      <section className="border-border bg-card mt-5 max-w-md rounded-xl border p-6">
        <CircleCheck aria-hidden size={36} className="text-emerald-500" />
        <p className="mt-3 text-lg font-semibold">
          {t("paid", { amount: formatUsdt(deposit.amount, locale) })}
        </p>
        <p className="text-tx-mute text-sm">{t("credited")}</p>
        <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          <dt className="text-tx-dim">{t("network")}</dt>
          <dd>{networkLabel(deposit.network)}</dd>
          {deposit.closed_at !== null && (
            <>
              <dt className="text-tx-dim">{t("paidAt")}</dt>
              <dd>{formatMoment(deposit.closed_at, locale)}</dd>
            </>
          )}
          {deposit.tx_id !== null && (
            <>
              <dt className="text-tx-dim">{t("tx")}</dt>
              <dd>
                <a
                  href={explorerTxLink(deposit.network, deposit.tx_id)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary-ink font-mono underline-offset-4 hover:underline"
                >
                  {shortHash(deposit.tx_id)}
                </a>
              </dd>
            </>
          )}
        </dl>
        {again}
      </section>
    );

  return (
    <section className="border-border bg-card mt-5 max-w-md rounded-xl border p-6">
      <p className="text-sm leading-relaxed">{t("expired", { number: deposit.number })}</p>
      <div className="flex flex-wrap gap-x-3">
        {again}
        <a href={supportHref} target="_blank" rel="noopener noreferrer" className={BUTTON}>
          {t("support")}
        </a>
      </div>
    </section>
  );
}
