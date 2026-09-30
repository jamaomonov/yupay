import { type Dispatch, type SetStateAction, useCallback, useEffect, useRef } from "react";

/** The wallet's method id in every checkout (not an acquirer). */
const WALLET = "wallet";

/**
 * Which payment method to show selected, given whether the balance can pay.
 *
 * A signed-in buyer whose balance covers the order starts on «Баланс» — the
 * one method that needs no redirect and no card (owner, 2026-09-30). If the
 * order then grows past the balance, an automatic choice goes back to the
 * default acquirer. A method the buyer picked by hand is never changed.
 */
export function preferBalance(
  current: string,
  o: { ready: boolean; picked: boolean; fallback: string },
): string {
  if (o.picked) return current;
  if (o.ready) return WALLET;
  return current === WALLET ? o.fallback : current;
}

/**
 * Applies `preferBalance` to a checkout's method state whenever the balance's
 * readiness changes. Returns the function a method tile calls on a tap, which
 * marks the choice as the buyer's own.
 */
export function usePreferBalance(
  ready: boolean,
  setMethodId: Dispatch<SetStateAction<string>>,
  fallback: string,
): () => void {
  const picked = useRef(false);
  useEffect(() => {
    setMethodId((current) => preferBalance(current, { ready, picked: picked.current, fallback }));
  }, [ready, fallback, setMethodId]);
  return useCallback(() => {
    picked.current = true;
  }, []);
}
