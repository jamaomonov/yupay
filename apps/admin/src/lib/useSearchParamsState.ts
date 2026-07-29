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

export function useSearchParamsState<T = string>(
  key: string,
  defaultValue: T,
  codec?: SearchParamCodec<T>,
): [T, (next: T) => void] {
  const [params, setParams] = useSearchParams();
  const effective: SearchParamCodec<T> = codec ?? (stringCodec as unknown as SearchParamCodec<T>);

  const raw = params.get(key);
  const value: T = raw === null ? defaultValue : effective.parse(raw);

  // Uses the functional-updater form of `setSearchParams` (reads `prev`
  // rather than the `params` closed over at render time) so that firing
  // several of these setters back-to-back in one handler — e.g. a "reset
  // filters" button clearing status + date range + offset together —
  // composes correctly instead of each call clobbering the others' writes
  // with its own stale snapshot of the URL.
  const setValue = useCallback(
    (next: T) => {
      setParams(
        (prev) => {
          const updated = new URLSearchParams(prev);
          const isDefault = effective.isDefault?.(next) ?? next === defaultValue;
          if (isDefault) {
            updated.delete(key);
          } else {
            updated.set(key, effective.serialize(next));
          }
          return updated;
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
