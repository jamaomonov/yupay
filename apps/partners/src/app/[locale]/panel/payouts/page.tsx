"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { formatMoney, formatUzs } from "@/lib/money";
import { useBalance, usePayouts } from "@/lib/panel";

/** The floor the API enforces. Stated here **before** submission, not only
 *  discovered by being rejected after typing a card number in. */
const MINIMUM_UZS = 50_000;

const STATUS_KEYS: Record<string, string> = {
  requested: "payoutStatusRequested",
  approved: "payoutStatusRequested",
  paid: "payoutStatusPaid",
  rejected: "payoutStatusRejected",
};

type State = "idle" | "sending" | "done" | "err-min" | "err-balance" | "err-generic";

export default function PayoutsPage() {
  const t = useTranslations("partners.panel");
  const queryClient = useQueryClient();
  const balance = useBalance();
  const payouts = usePayouts();
  const [state, setState] = useState<State>("idle");

  const available = Number(balance.data?.available ?? "0");

  async function submit(event: React.SyntheticEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (state === "sending") return;
    const form = new FormData(event.currentTarget);
    const raw = form.get("amount");
    const card = form.get("card");
    const holder = form.get("holder");
    if (typeof raw !== "string" || typeof card !== "string" || typeof holder !== "string") return;

    const amount = Number(raw);
    // Checked here as well as on the server. The server is authoritative, but
    // finding out after typing a card number is a worse way to learn it.
    if (!Number.isFinite(amount) || amount < MINIMUM_UZS) {
      setState("err-min");
      return;
    }
    if (amount > available) {
      setState("err-balance");
      return;
    }

    setState("sending");
    try {
      await api("/api/v1/affiliate/payouts", {
        method: "POST",
        body: { amount: raw, card_number: card, card_holder: holder },
        idempotencyKey: crypto.randomUUID(),
      });
      setState("done");
      // The balance moved — the requested amount is now reserved rather than
      // available — so both reads are stale.
      await queryClient.invalidateQueries({ queryKey: ["balance"] });
      await queryClient.invalidateQueries({ queryKey: ["payouts"] });
    } catch (err) {
      setState(err instanceof ApiError && err.status === 409 ? "err-balance" : "err-generic");
    }
  }

  const message =
    state === "err-min"
      ? t("payoutErrMin")
      : state === "err-balance"
        ? t("payoutErrBalance")
        : state === "err-generic"
          ? t("payoutErrGeneric")
          : null;

  const field =
    "border-border bg-card focus:border-primary/60 h-12 w-full rounded-full border px-5 text-[15px] outline-none transition";
  const rows = payouts.data?.items ?? [];

  return (
    <div className="space-y-8">
      <section className="border-border border-y py-7">
        <h2 className="font-display text-lg font-bold">{t("payoutTitle")}</h2>
        <p className="text-tx-mute mt-1 text-[13px]">
          {t("available")}: <span className="text-primary font-mono">{formatUzs(available)}</span>
        </p>

        {state === "done" ? (
          <p className="border-primary/40 bg-primary/5 mt-5 rounded-2xl border p-4 text-[14px]">
            {t("payoutDone")}
          </p>
        ) : (
          <form onSubmit={(e) => void submit(e)} className="mt-5 space-y-4">
            <label className="block">
              <span className="text-tx-mute mb-2 block text-[13px]">{t("payoutAmount")}</span>
              <input
                name="amount"
                type="number"
                inputMode="numeric"
                min={MINIMUM_UZS}
                max={available}
                step={1}
                required
                className={field}
              />
              <span className="text-tx-dim mt-1.5 block text-[12px]">
                {t("payoutMin", { amount: formatUzs(MINIMUM_UZS) })}
              </span>
            </label>
            <label className="block">
              <span className="text-tx-mute mb-2 block text-[13px]">{t("payoutCard")}</span>
              <input
                name="card"
                type="text"
                inputMode="numeric"
                minLength={12}
                maxLength={32}
                required
                autoComplete="off"
                className={`${field} font-mono`}
              />
            </label>
            <label className="block">
              <span className="text-tx-mute mb-2 block text-[13px]">{t("payoutHolder")}</span>
              <input name="holder" type="text" maxLength={128} required className={field} />
            </label>

            {message !== null && <p className="text-[13px] text-red-400">{message}</p>}

            <button
              type="submit"
              disabled={state === "sending" || available < MINIMUM_UZS}
              className="bg-primary text-primary-foreground h-12 w-full rounded-full text-[15px] font-bold transition hover:brightness-110 disabled:opacity-50"
            >
              {state === "sending" ? t("payoutSubmitting") : t("payoutSubmit")}
            </button>
          </form>
        )}
      </section>

      {payouts.isSuccess && rows.length === 0 ? (
        <p className="text-tx-mute text-[14px]">{t("payoutsEmpty")}</p>
      ) : (
        <section className="border-border overflow-x-auto border-y">
          <table className="w-full min-w-[560px] border-collapse">
            <thead>
              <tr className="border-border text-tx-mute border-b text-left">
                <th className="px-4 py-3 text-[13px] font-medium">{t("colDate")}</th>
                <th className="px-4 py-3 text-[13px] font-medium">{t("colAmount")}</th>
                <th className="px-4 py-3 text-[13px] font-medium">{t("payoutCard")}</th>
                <th className="px-4 py-3 text-[13px] font-medium">{t("colStatus")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-border/60 border-b last:border-0">
                  <td className="text-tx-mute px-4 py-3 font-mono text-[13px]">
                    {new Date(row.created_at).toLocaleDateString("ru-RU")}
                  </td>
                  <td className="px-4 py-3 font-mono text-[13px]">
                    {formatMoney(row.amount, row.currency)}
                  </td>
                  {/* Only the last four ever reach the browser — the API
                      returns nothing more, deliberately. */}
                  <td className="text-tx-mute px-4 py-3 font-mono text-[13px]">
                    {t("cardMask", { last4: row.card_last4 })}
                  </td>
                  <td className="text-tx-mute px-4 py-3 text-[13px]">
                    {t(STATUS_KEYS[row.status] ?? "payoutStatusRequested")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
