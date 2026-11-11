"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "./api";
import { acceptPoll, type Phase, secondsLeft } from "./p2p";
import { usdtErrorKey, usdtPhase, usdtPollDeadline } from "./usdt";

import type { UsdtDeposit, UsdtDepositsPage } from "./types";

import { useCabinet } from "@/components/CabinetContext";

const POLL_MS = 5000;

export interface UsdtFlow {
  deposit: UsdtDeposit | null;
  phase: Phase;
  /** The amount box, as typed (sanitised). */
  amount: string;
  setAmount: (value: string) => void;
  error: string | null;
  busy: boolean;
  /** The server said the method is off for this reseller. */
  disabled: boolean;
  nowMs: number;
  submit: () => Promise<void>;
  cancel: () => Promise<void>;
  /** Forget the outcome on screen and start over. */
  reset: () => void;
}

/**
 * A USDT top-up's state: restore, reserve, poll, cancel — the card flow's rules
 * (one Idempotency-Key per intent, an epoch that stale polls must match).
 */
export function useUsdtDeposit(enabled: boolean): UsdtFlow {
  const t = useTranslations("merchant.topUpUsdt");
  const { usdt, refreshProfile } = useCabinet();
  const [deposit, setDeposit] = useState<UsdtDeposit | null>(null);
  const [amount, setAmountState] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [disabled, setDisabled] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const intentKey = useRef<string | null>(null);
  const epoch = useRef(0);

  const load = useCallback(async (number: string) => {
    const started = epoch.current;
    const fresh = await api<UsdtDeposit>(`/usdt/deposits/${encodeURIComponent(number)}`);
    const cancelled = epoch.current !== started;
    setDeposit((prev) =>
      acceptPoll(prev?.number ?? null, fresh.number, cancelled) ? fresh : prev,
    );
  }, []);

  // Restore an open top-up after a reload; the list never carries the address.
  useEffect(() => {
    if (!enabled) return;
    void api<UsdtDepositsPage>("/usdt/deposits?limit=1")
      .then(async (page) => {
        const first = page.items[0];
        if (first?.status === "pending") await load(first.number);
      })
      .catch(() => undefined);
  }, [enabled, load]);

  const phase = usdtPhase(deposit);
  const number = deposit?.number ?? null;
  const left = deposit === null ? 1 : secondsLeft(deposit.expires_at, nowMs);
  const pollUntil = usdtPollDeadline(deposit);

  useEffect(() => {
    if (phase !== "details") return undefined;
    setNowMs(Date.now());
    const tick = setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => {
      clearInterval(tick);
    };
  }, [phase]);

  // Poll while pending and ten minutes past expiry: the block time decides a
  // match, so an on-time transfer read late still credits.
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
    if (phase === "details" && number !== null && left === 0)
      void load(number).catch(() => undefined);
  }, [phase, number, left, load]);

  useEffect(() => {
    if (phase === "paid") refreshProfile();
  }, [phase, refreshProfile]);

  const setAmount = useCallback((value: string) => {
    setAmountState(value);
    intentKey.current = null;
  }, []);

  const failed = async (caught: unknown) => {
    if (!(caught instanceof ApiError)) {
      setError(t("errBusy"));
    } else if (caught.code === "usdt_reservation_open") {
      intentKey.current = null;
      const open = caught.body.number;
      try {
        if (typeof open === "string") await load(open);
        else setError(t("errOpen"));
      } catch {
        setError(t("errOpen"));
      }
    } else if (caught.code === "usdt_disabled") {
      setDisabled(true);
    } else if (caught.code === "usdt_amount_out_of_bounds") {
      const { min_amount: min, max_amount: max } = caught.body;
      setError(
        t("range", {
          min: typeof min === "string" ? min : (usdt?.min_amount ?? ""),
          max: typeof max === "string" ? max : (usdt?.max_amount ?? ""),
        }),
      );
    } else {
      if (caught.code === "usdt_idempotency_mismatch") intentKey.current = null;
      const key = usdtErrorKey(caught.code);
      setError(t(key ?? "errBusy"));
    }
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    intentKey.current ??= crypto.randomUUID();
    try {
      const created = await api<UsdtDeposit>("/usdt/deposits", {
        method: "POST",
        body: { amount },
        idempotencyKey: intentKey.current,
      });
      intentKey.current = null;
      setDeposit(created);
    } catch (caught) {
      await failed(caught);
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (number === null) return;
    setBusy(true);
    setError(null);
    try {
      await api<UsdtDeposit>(`/usdt/deposits/${encodeURIComponent(number)}/cancel`, {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
      });
      epoch.current += 1;
      intentKey.current = null;
      setDeposit(null);
    } catch (caught) {
      if (caught instanceof ApiError) {
        // Already closed on the server: show whatever it is now.
        await load(number).catch(() => undefined);
      } else {
        setError(t("errCancel"));
      }
    } finally {
      setBusy(false);
    }
  };

  const reset = useCallback(() => {
    epoch.current += 1;
    intentKey.current = null;
    setDeposit(null);
    setAmountState("");
    setError(null);
  }, []);

  return {
    deposit,
    phase,
    amount,
    setAmount,
    error,
    busy,
    disabled,
    nowMs,
    submit,
    cancel,
    reset,
  };
}
