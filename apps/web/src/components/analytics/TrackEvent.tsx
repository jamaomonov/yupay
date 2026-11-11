"use client";

import { useEffect, useRef } from "react";

import { type AnalyticsEvent, pushAnalyticsEvent } from "@/lib/analytics-events";

interface TrackEventProps {
  /** Built on the server — a plain object, so it crosses into the client as a prop. */
  event: AnalyticsEvent | null;
  /** What makes this a new view: the event goes out once per key, however
   *  often the component re-renders (a brand page sends `view_item` once). */
  dedupeKey: string;
}

/** Pushes `event` into the data layer once per `dedupeKey`. Renders nothing. */
export function TrackEvent({ event, dedupeKey }: TrackEventProps) {
  const sent = useRef<string | null>(null);
  useEffect(() => {
    if (sent.current === dedupeKey) return;
    sent.current = dedupeKey;
    pushAnalyticsEvent(event);
  }, [dedupeKey, event]);
  return null;
}
