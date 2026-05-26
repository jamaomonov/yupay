/** Tiny debounce hook used by combobox-style search inputs.
 *
 * Returns ``value`` after it's been stable for ``delay`` ms. Resets the
 * timer on every change. Cleared on unmount.
 *
 * Trade-off versus a ``useDeferredValue`` — debounce is explicit about
 * latency (caller can pick 150 ms for SKU search, 300 ms for cross-supplier
 * fetches), whereas ``useDeferredValue`` only kicks in when there's
 * actual paint pressure. We need the explicit guarantee. */

import { useEffect, useState } from "react";

export function useDebouncedValue<T>(value: T, delay = 200): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebounced(value);
    }, delay);
    return () => {
      window.clearTimeout(t);
    };
  }, [value, delay]);
  return debounced;
}
