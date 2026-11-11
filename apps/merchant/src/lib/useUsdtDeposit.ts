"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "./api";
import { acceptPoll, type Phase, secondsLeft } from "./p2p";
import { usdtErrorKey, usdtPhase, usdtPollDeadline } from "./usdt";

import type { UsdtDeposit, UsdtDepositsPage, UsdtNetwork } from "./types";

import { useCabinet } from "@/components/CabinetContext";

const POLL_MS = 5000;

/** Refusals about the amount itself: the chain picker steps back to the amount box. */
const AMOUNT_CODES: ReadonlySet<string> = new Set([
  "usdt_amount_taken",
  "usdt_amount_busy",
  "usdt_amount_precision",
  "usdt_amount_out_of_bounds",
]);

export interface UsdtOffer {
  /** What the reseller asked for, as sent. */
  asked: string;
  /** A free amount near it, e.g. "100.37". Nothing is held until accepted. */
  suggested: string;
  /** The chain the reseller picked; accepting reserves on the same one. */
  network: UsdtNetwork;
}

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
  /** The open chains, in display order. */
  networks: readonly UsdtNetwork[];
  /** The amount is set and more than one chain is open: the reseller picks one. */
  choosing: boolean;
  /** Amount → the chain picker, or straight to a reservation when one chain is open. */
  submit: () => Promise<void>;
  /** Reserve the amount on that chain. */
  pickNetwork: (network: UsdtNetwork) => Promise<void>;
  /** From the chain picker back to the amount box. */
  backToAmount: () => void;
  /**
   * The asked amount is held by another top-up: the server offers a free one
   * near it. `null` when there is no offer on screen.
   */
  offer: UsdtOffer | null;
  /** Reserve the offered amount. */
  acceptOffer: () => Promise<void>;
  /** Back to the amount box to change it. */
  declineOffer: () => void;
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
  const { usdt, refreshProfile, refreshUsdt } = useCabinet();
  const networks = usdt?.networks ?? [];
  const [deposit, setDeposit] = useState<UsdtDeposit | null>(null);
  const [amount, setAmountState] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [offer, setOffer] = useState<UsdtOffer | null>(null);
  const [choosing, setChoosing] = useState(false);
  const [disabled, setDisabled] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const intentKey = useRef<string | null>(null);
  const intentOf = useRef(""); // what the key was minted for: amount and chain
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
    setOffer(null);
    intentKey.current = null;
  }, []);

  const failed = async (caught: unknown, asked: string, network: UsdtNetwork) => {
    // An answer about the amount is read where the amount is typed.
    if (caught instanceof ApiError && AMOUNT_CODES.has(caught.code ?? "")) setChoosing(false);
    if (caught instanceof ApiError && caught.code === "usdt_amount_taken") {
      intentKey.current = null;
      const suggested = caught.body.suggested;
      if (typeof suggested === "string") setOffer({ asked, suggested, network });
      else setError(t("errAmountBusy"));
    } else if (!(caught instanceof ApiError)) {
      setError(t("errBusy"));
    } else if (caught.code === "usdt_network_disabled") {
      // Switched off since the status was read: pick again from a fresh list.
      intentKey.current = null;
      setChoosing(networks.length > 1);
      setError(t("errNetworkOff"));
      refreshUsdt();
    } else if (caught.code === "usdt_reservation_open") {
      intentKey.current = null;
      setChoosing(false);
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

  const reserve = async (value: string, network: UsdtNetwork) => {
    setBusy(true);
    setError(null);
    setOffer(null);
    // Another amount or chain is a new intent: the old key would be a mismatch.
    const of = `${value}|${network}`;
    if (intentOf.current !== of) intentKey.current = null;
    intentOf.current = of;
    intentKey.current ??= crypto.randomUUID();
    try {
      const created = await api<UsdtDeposit>("/usdt/deposits", {
        method: "POST",
        body: { amount: value, network },
        idempotencyKey: intentKey.current,
      });
      intentKey.current = null;
      setChoosing(false);
      setDeposit(created);
    } catch (caught) {
      await failed(caught, value, network);
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    setError(null);
    const only = networks.length === 1 ? networks[0] : undefined;
    if (only === undefined) setChoosing(true);
    else await reserve(amount, only);
  };

  const pickNetwork = (network: UsdtNetwork) => reserve(amount, network);

  const backToAmount = useCallback(() => {
    setChoosing(false);
    setError(null);
  }, []);

  const acceptOffer = async () => {
    if (offer === null) return;
    setAmountState(offer.suggested);
    await reserve(offer.suggested, offer.network);
  };

  const declineOffer = useCallback(() => {
    setOffer(null);
  }, []);

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
    setOffer(null);
    setChoosing(false);
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
    networks,
    choosing,
    submit,
    pickNetwork,
    backToAmount,
    offer,
    acceptOffer,
    declineOffer,
    cancel,
    reset,
  };
}
