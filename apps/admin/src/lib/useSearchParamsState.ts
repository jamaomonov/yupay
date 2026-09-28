/**
 * `useSearchParamsState` — typed two-way binding between a single URL search-param and
 * React state.
 *
 * Why a hook and not raw `useSearchParams`:
 *  - Default values stay *out* of the URL (clean URLs, no `?status=&q=&offset=0`).
 *  - History entries are replaced, not pushed — typing in a filter doesn't pollute back/forward.
 *  - Strict `parse` / `serialize` keep callers honest about the runtime shape.
 *
 * Per ADR-0017 this is the building block for migrating list-page filters from local
 * `useState` to the URL so views are shareable and survive reload.
 */

import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

export interface SearchParamCodec<T> {
  parse: (raw: string) => T;
  serialize: (value: T) => string;
  /** Treat ``true`` values as "back to default" and remove the param from the URL. */
  isDefault?: (value: T) => boolean;
}

const stringCodec: SearchParamCodec<string> = {
  parse: (raw) => raw,
  serialize: (v) => v,
  isDefault: (v) => v === "",
};

/** The search params written so far in the current tick (see `setValue`). */
let pending: URLSearchParams | null = null;

export function useSearchParamsState<T = string>(
  key: string,
  defaultValue: T,
  codec?: SearchParamCodec<T>,
): [T, (next: T) => void] {
  const [params, setParams] = useSearchParams();
  const effective: SearchParamCodec<T> = codec ?? (stringCodec as unknown as SearchParamCodec<T>);

  const raw = params.get(key);
  const value: T = raw === null ? defaultValue : effective.parse(raw);

  // Setters fired back-to-back in one handler — a filter change plus a page reset,
  // "reset filters" clearing several keys — must compose. `setSearchParams`' functional
  // updater does NOT queue: react-router hands every call the same location, so each
  // write used to clobber the one before it (a filter + `offset` reset lost the filter).
  // The writes of one tick therefore accumulate in `pending` and each navigation
  // carries all of them; the last one wins with the full set.
  const setValue = useCallback(
    (next: T) => {
      setParams(
        (prev) => {
          const updated = new URLSearchParams(pending ?? prev);
          const isDefault = effective.isDefault?.(next) ?? next === defaultValue;
          if (isDefault) {
            updated.delete(key);
          } else {
            updated.set(key, effective.serialize(next));
          }
          if (pending === null) {
            queueMicrotask(() => {
              pending = null;
            });
          }
          pending = updated;
          return new URLSearchParams(updated);
        },
        { replace: true },
      );
    },
    [setParams, key, defaultValue, effective],
  );

  return [value, setValue];
}

export const numberCodec: SearchParamCodec<number> = {
  parse: (raw) => {
    const n = Number(raw);
    return Number.isFinite(n) ? n : 0;
  },
  serialize: (v) => v.toString(),
  isDefault: (v) => v === 0,
};
