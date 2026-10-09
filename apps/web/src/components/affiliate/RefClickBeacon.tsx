"use client";

import { useEffect } from "react";

import { reportRefClick } from "@/lib/ref-click";

const API = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** Counts a landing on a partner link (`?ref=CODE`). Renders nothing. */
export function RefClickBeacon() {
  useEffect(() => {
    void reportRefClick(API);
  }, []);
  return null;
}
