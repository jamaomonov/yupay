"use client";

import { Wallet } from "lucide-react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import type { P2PDeposit, P2PDepositsPage } from "@/lib/types";

import { useCabinet } from "@/components/CabinetContext";
import { CardAmountForm } from "@/components/CardAmountForm";
import { PageHeading } from "@/components/PageHeading";
import { TopUpDetails } from "@/components/TopUpDetails";
import { type TopUpMethod, TopUpMethods } from "@/components/TopUpMethods";
import { UsdtTopUp } from "@/components/UsdtTopUp";
import { api, ApiError } from "@/lib/api";
import { acceptPoll, errorKey, phase, pollDeadline, secondsLeft } from "@/lib/p2p";
import { useUsdtDeposit } from "@/lib/useUsdtDeposit";

const SUPPORT = "https://t.me/yupay_support";
const POLL_MS = 3000;

/**
 * Self-serve top-up: pick a method (card or USDT), then the amount, then the
 * exact amount and where to send it with a clock, then the outcome.
 */
export default function TopUp() {
  const t = useTranslations("merchant.topUp");
  const { locale } = useParams<{ locale: string }>();
  const { p2p, usdt: usdtStatus, refreshProfile } = useCabinet();
  const [deposit, setDeposit] = useState<P2PDeposit | null>(null);
  const [method, setMethod] = useState<TopUpMethod | null>(null);
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [disabled, setDisabled] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  // One key per intent: kept across retries of the same amount, dropped when the
  // amount changes or the intent is done.
  const intentKey = useRef<string | null>(null);
  // Bumped by every cancel and "top up again": a poll that left before it and
  // lands after must not put the old reservation back on screen.
  const epoch = useRef(0);

  const load = useCallback(async (number: string) => {
    const started = epoch.current;
    const fresh = await api<P2PDeposit>(`/p2p/deposits/${encodeURIComponent(number)}`);
    const cancelled = epoch.current !== started;
    setDeposit((prev) =>
      acceptPoll(prev?.number ?? null, fresh.number, cancelled) ? fresh : prev,
    );
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
  const pollUntil = pollDeadline(deposit);

  useEffect(() => {
    if (current !== "details") return undefined;
    // The first frame must already read the real clock, not the one from mount.
    setNowMs(Date.now());
    const tick = setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => {
      clearInterval(tick);
    };
  }, [current]);

  // Poll while pending and, after expiry, until the quarantine ends: a late
  // delivery of an on-time transfer can still credit it. Once more the moment
  // the clock reaches zero.
  useEffect(() => {
    if (pollUntil === null || number === null) return undefined;
    const poll = setInterval(() => {
      if (Date.now() >= pollUntil) {
        clearInterval(poll);
        return;
      }
      void load(number).catch(() => undefined);
    }, POLL_MS);
    return () => {
      clearInterval(poll);
    };
  }, [pollUntil, number, load]);
  useEffect(() => {
    if (current === "details" && number !== null && left === 0)
      void load(number).catch(() => undefined);
  }, [current, number, left, load]);

  useEffect(() => {
    if (current === "paid") refreshProfile();
  }, [current, refreshProfile]);

  const usdtEnabled = usdtStatus?.enabled === true;
  const usdt = useUsdtDeposit(usdtEnabled);
  const cardOn = enabled && !disabled;
  const usdtOn = usdtEnabled && !usdt.disabled;
  // A reservation of either kind on screen hides the picker and the other flow.
  const cardIdle = current === "amount" || current === "cancelled";
  const usdtIdle = usdt.phase === "amount" || usdt.phase === "cancelled";
  const idle = cardIdle && usdtIdle;
  const unavailable =
    !cardOn && !usdtOn && ((p2p !== null && usdtStatus !== null) || disabled || usdt.disabled);

  const submit = async () => {
    setBusy(true);
    setError(null);
    intentKey.current ??= crypto.randomUUID();
    try {
      const created = await api<P2PDeposit>("/p2p/deposits", {
        method: "POST",
        body: { amount_uzs: Number(amount) },
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
    setError(null);
    try {
      await api<P2PDeposit>(`/p2p/deposits/${encodeURIComponent(number)}/cancel`, {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
      });
      epoch.current += 1;
      intentKey.current = null;
      setDeposit(null);
      setWaiting(false);
    } catch (caught) {
      if (caught instanceof ApiError) {
        // Already closed on the server: show whatever it is now.
        await load(number).catch(() => undefined);
      } else {
        // Network: the reservation is still open, so keep its details up.
        setError(t("errCancel"));
      }
    } finally {
      setBusy(false);
    }
  };

  const again = () => {
    epoch.current += 1;
    intentKey.current = null;
    setDeposit(null);
    setMethod(null);
    setAmount("");
    setError(null);
    setWaiting(false);
  };
  const againButton = (
    <button
      type="button"
      onClick={again}
      className="bg-primary text-primary-foreground rounded-btn mt-4 inline-flex px-4 py-2 text-sm font-semibold"
    >
      {t("again")}
    </button>
  );

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
      {unavailable && (
        <section className="mt-5">
          <p className="text-tx-mute text-sm">{t("unavailable")}</p>
          {supportLink}
        </section>
      )}
      {idle && method === null && (cardOn || usdtOn) && (
        <TopUpMethods
          card={cardOn}
          usdt={usdtOn}
          usdtNetworks={usdtStatus?.networks ?? []}
          onPick={setMethod}
        />
      )}
      {idle && method === "card" && cardOn && (
        <CardAmountForm
          amount={amount}
          onAmount={(digits) => {
            setAmount(digits);
            intentKey.current = null;
          }}
          fxRate={p2p.fx_rate}
          locale={locale}
          busy={busy}
          error={error}
          onSubmit={() => {
            void submit();
          }}
          onBack={() => {
            setMethod(null);
            setError(null);
          }}
        />
      )}
      {cardIdle && usdtOn && (method === "usdt" || !usdtIdle) && (
        <UsdtTopUp
          flow={usdt}
          locale={locale}
          supportHref={SUPPORT}
          onBack={() => {
            setMethod(null);
          }}
          onAgain={() => {
            setMethod(null);
          }}
        />
      )}
      {current === "details" && deposit !== null && (
        <TopUpDetails
          deposit={deposit}
          nowMs={nowMs}
          locale={locale}
          waiting={waiting}
          busy={busy}
          error={error}
          onCancel={() => {
            void cancel();
          }}
          onPaid={() => {
            setWaiting(true);
          }}
        />
      )}
      {current === "paid" && deposit !== null && (
        <section className="border-border bg-card mt-5 max-w-md rounded-xl border p-6">
          <p className="font-semibold">{t("paid", { usd: deposit.amount_usd })}</p>
          {againButton}
        </section>
      )}
      {current === "expired" && deposit !== null && (
        <section className="border-border bg-card mt-5 max-w-md rounded-xl border p-6">
          <p className="text-sm leading-relaxed">{t("expired", { number: deposit.number })}</p>
          <div className="flex flex-wrap gap-x-3">
            {againButton}
            {supportLink}
          </div>
        </section>
      )}
    </div>
  );
}
