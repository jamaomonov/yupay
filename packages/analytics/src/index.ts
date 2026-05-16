/**
 * Provider-agnostic analytics interface. The web app uses Plausible by default; the Mini
 * App may use a different backend. Both surfaces import the same `track()` function and
 * use the same event names — drift is forbidden.
 */

export interface AnalyticsBackend {
  track: (name: string, props?: Record<string, string | number | boolean>) => void;
}

let backend: AnalyticsBackend = {
  track() {
    // no-op by default; production wiring is set via setBackend()
  },
};

export function setBackend(impl: AnalyticsBackend): void {
  backend = impl;
}

export function track(name: string, props?: Record<string, string | number | boolean>): void {
  backend.track(name, props);
}
