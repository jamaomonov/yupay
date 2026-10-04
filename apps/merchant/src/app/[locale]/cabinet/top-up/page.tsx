"use client";

import { Wallet } from "lucide-react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import type { P2PDeposit, P2PDepositsPage } from "@/lib/types";

import { useCabinet } from "@/components/CabinetContext";
import { PageHeading } from "@/components/PageHeading";
import { TopUpDetails } from "@/components/TopUpDetails";
import { api, ApiError } from "@/lib/api";
import { errorKey, phase, secondsLeft, usdPreview } from "@/lib/p2p";

const SUPPORT = "https://t.me/yupay_support";
const POLL_MS = 3000;

/** Self-serve top-up: amount, then the exact amount and card with a clock, then the outcome. */
export default function TopUp() {
  const t = useTranslations("merchant.topUp");
  const { locale } = useParams<{ locale: string }>();
  const { p2p, refreshProfile } = useCabinet();
  const [deposit, setDeposit] = useState<P2PDeposit | null>(null);
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [disabled, setDisabled] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  // One key per intent: kept across retries of the same amount, dropped when the
  // amount changes or the intent is done.
  const intentKey = useRef<string | null>(null);

  const load = useCallback(async (number: string) => {
    setDeposit(await api<P2PDeposit>(`/p2p/deposits/${encodeURIComponent(number)}`));
  }, []);

  // Restore an open top-up after a reload.
  const enabled = p2p?.enabled === true;
  useEffect(() => {
    if (!enabled) return;
    void api<P2PDepositsPage>("/p2p/deposits?limit=1")
      .then(async (page) => {
        const first = page.items[0];
        if (first?.status === "pending") await load(first.number);
      })
      .catch(() => undefined);
  }, [enabled, load]);

  const current = phase(deposit);
  const number = deposit?.number ?? null;
  const left = deposit === null ? 1 : secondsLeft(deposit.expires_at, nowMs);

  useEffect(() => {
    if (current !== "details") return undefined;
    const tick = setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => {
      clearInterval(tick);
    };
  }, [current]);

  // Poll while pending, and once more the moment the clock reaches zero.
  useEffect(() => {
    if (current !== "details" || number === null) return undefined;
    const poll = setInterval(() => {
      void load(number).catch(() => undefined);
    }, POLL_MS);
    return () => {
      clearInterval(poll);
    };
  }, [current, number, load]);
  useEffect(() => {
    if (current === "details" && number !== null && left === 0)
      void load(number).catch(() => undefined);
  }, [current, number, left, load]);

  useEffect(() => {
    if (current === "paid") refreshProfile();
  }, [current, refreshProfile]);

  const value = Number(amount);
  const preview = usdPreview(value, p2p?.fx_rate ?? null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    intentKey.current ??= crypto.randomUUID();
    try {
      const created = await api<P2PDeposit>("/p2p/deposits", {
        method: "POST",
        body: { amount_uzs: value },
        idempotencyKey: intentKey.current,
      });
      intentKey.current = null;
      setWaiting(false);
      setDeposit(created);
    } catch (caught) {
      if (!(caught instanceof ApiError)) {
        setError(t("errBusy"));
      } else if (caught.code === "p2p_reservation_open") {
        // That intent is answered; a later submit is a new one.
        intentKey.current = null;
        const open = caught.body.number;
        try {
          if (typeof open === "string") await load(open);
          else setError(t("errOpen"));
        } catch {
          setError(t("errOpen"));
        }
      } else if (caught.code === "p2p_disabled") {
        setDisabled(true);
      } else {
        const key = errorKey(caught.code);
        setError(key === null ? t("errBusy") : t(key));
      }
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (number === null) return;
    setBusy(true);
    try {
      await api<P2PDeposit>(`/p2p/deposits/${encodeURIComponent(number)}/cancel`, {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
      });
      intentKey.current = null;
      setDeposit(null);
      setWaiting(false);
    } catch {
      // Already closed on the server: show whatever it is now.
      await load(number).catch(() => undefined);
    } finally {
      setBusy(false);
    }
  };

  const supportLink = (
    <a
      href={SUPPORT}
      target="_blank"
      rel="noopener noreferrer"
      className="bg-primary text-primary-foreground rounded-btn mt-4 inline-flex px-4 py-2 text-sm font-semibold"
    >
      {t("support")}
    </a>
  );

  return (
    <div>
      <PageHeading icon={Wallet} title={t("title")} />
      {(disabled || p2p?.enabled === false) && (
        <section className="mt-5">
          <p className="text-tx-mute text-sm">{t("unavailable")}</p>
          {supportLink}
        </section>
      )}
      {enabled && !disabled && (current === "amount" || current === "cancelled") && (
        <form
          className="border-border bg-card mt-5 max-w-md rounded-xl border p-6"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <label className="text-tx-dim text-xs" htmlFor="topup-amount">
            {t("amountLabel")}
          </label>
          <input
            id="topup-amount"
            inputMode="numeric"
            autoComplete="off"
            value={amount}
            onChange={(event) => {
              setAmount(event.target.value.replace(/\D/g, ""));
              intentKey.current = null;
            }}
            className="border-border bg-card-2 rounded-btn mt-1.5 block w-full border px-3 py-2 font-mono text-lg"
          />
          {preview !== null && (
            <p className="text-tx-mute mt-2 text-sm">
              {t("usdPreview", { usd: preview, rate: p2p.fx_rate ?? "" })}
            </p>
          )}
          {error !== null && (
            <p role="alert" className="mt-3 text-sm text-red-500">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={busy || !(value > 0)}
            className="bg-primary text-primary-foreground rounded-btn mt-4 px-4 py-2 text-sm font-semibold disabled:opacity-50"
          >
            {t("continue")}
          </button>
        </form>
      )}
      {current === "details" && deposit !== null && (
        <TopUpDetails
          deposit={deposit}
          nowMs={nowMs}
          locale={locale}
          waiting={waiting}
          busy={busy}
          onCancel={() => {
            void cancel();
          }}
          onPaid={() => {
            setWaiting(true);
          }}
        />
      )}
      {current === "paid" && deposit !== null && (
        <p className="border-border bg-card mt-5 max-w-md rounded-xl border p-6 font-semibold">
          {t("paid", { usd: deposit.amount_usd })}
        </p>
      )}
      {current === "expired" && deposit !== null && (
        <section className="border-border bg-card mt-5 max-w-md rounded-xl border p-6">
          <p className="text-sm leading-relaxed">{t("expired", { number: deposit.number })}</p>
          {supportLink}
        </section>
      )}
    </div>
  );
}
