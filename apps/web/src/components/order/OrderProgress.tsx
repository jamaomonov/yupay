"use client";

import { Check, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";

/** Where each of the three customer-visible stages stands. */
export type StepState = "done" | "active" | "upcoming";

/**
 * Statuses that belong on the happy-path timeline. Terminal-bad states
 * (failed / cancelled / expired / refunded) are NOT here on purpose: drawing a
 * "payment → fulfilment → delivered" track for a refunded order would imply
 * progress that isn't happening. `StatusBlock` explains those on its own.
 */
const TRACKED = ["pending_payment", "paid", "fulfilling", "fulfilled", "delivered"] as const;

export function isTrackedStatus(status: string): boolean {
  return (TRACKED as readonly string[]).includes(status);
}

/**
 * Map an order status onto the three stages: payment, fulfilment, delivery.
 *
 * `fulfilled` means the supplier finished but the artifact hasn't been handed
 * over yet, so stage 3 is the active one — not done.
 */
export function progressFor(status: string): [StepState, StepState, StepState] {
  switch (status) {
    case "pending_payment":
      return ["active", "upcoming", "upcoming"];
    case "paid":
    case "fulfilling":
      return ["done", "active", "upcoming"];
    case "fulfilled":
      return ["done", "done", "active"];
    case "delivered":
      return ["done", "done", "done"];
    default:
      return ["upcoming", "upcoming", "upcoming"];
  }
}

const DOT: Record<StepState, string> = {
  done: "bg-primary/15 text-primary ring-primary/30",
  active: "bg-blue/15 text-blue ring-blue/30",
  upcoming: "bg-muted text-tx-dim ring-border-2",
};

const LABEL: Record<StepState, string> = {
  done: "text-foreground",
  active: "text-foreground",
  upcoming: "text-tx-dim",
};

/**
 * Three-stage order timeline shown above the status hero.
 *
 * Answers "where is my order?" at a glance — the single status badge told the
 * customer the current state but not what comes next, which is the question
 * they actually have while waiting. `isTopUp` swaps the last label, since a
 * top-up is credited to an account rather than "delivered".
 */
export function OrderProgress({ status, isTopUp }: { status: string; isTopUp?: boolean }) {
  const t = useTranslations("web.orders");
  const states = progressFor(status);
  const steps = [
    { key: "paid", label: t("progress.paid"), state: states[0] },
    { key: "fulfilling", label: t("progress.fulfilling"), state: states[1] },
    {
      key: "delivered",
      label: isTopUp ? t("progress.credited") : t("progress.delivered"),
      state: states[2],
    },
  ];

  return (
    <ol className="flex items-start gap-1" aria-label={t("progress.label")}>
      {steps.map((step, i) => (
        <li key={step.key} className="flex flex-1 flex-col items-center gap-1.5 text-center">
          <div className="flex w-full items-center gap-1">
            {/* Connector into this dot — hidden on the first step. */}
            <span
              className={`h-px flex-1 ${i === 0 ? "opacity-0" : states[i - 1] === "done" ? "bg-primary/40" : "bg-border-2"}`}
              aria-hidden="true"
            />
            <span
              className={`flex size-7 shrink-0 items-center justify-center rounded-full ring-1 ring-inset ${DOT[step.state]}`}
              aria-hidden="true"
            >
              {step.state === "done" ? (
                <Check size={14} strokeWidth={3} />
              ) : step.state === "active" ? (
                <Loader2 size={14} strokeWidth={3} className="animate-spin" />
              ) : (
                <span className="size-1.5 rounded-full bg-current" />
              )}
            </span>
            {/* Connector out of this dot — hidden on the last step. */}
            <span
              className={`h-px flex-1 ${i === steps.length - 1 ? "opacity-0" : step.state === "done" ? "bg-primary/40" : "bg-border-2"}`}
              aria-hidden="true"
            />
          </div>
          <span className={`text-[11px] font-semibold leading-tight ${LABEL[step.state]}`}>
            {step.label}
          </span>
        </li>
      ))}
    </ol>
  );
}
