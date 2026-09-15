"use client";

import { useState } from "react";

import { Prose } from "@/components/docs/Prose";

export interface ResponsePanel {
  status: string;
  /** Explicitly `| undefined`: `exactOptionalPropertyTypes` makes `?` mean
   *  "may be absent", not "may be undefined", and the contract hands us the
   *  second. */
  description: string | undefined;
  /** Rendered by the server and handed over — the schema table and example. */
  body: React.ReactNode;
}

/** The tone of a status, so a reader finds the failure case by colour. */
function toneOf(status: string): string {
  if (status.startsWith("2")) return "text-primary-ink border-primary";
  if (status.startsWith("4")) return "text-danger border-danger";
  return "text-gold border-gold";
}

/**
 * Responses, one tab per status.
 *
 * Every declared status gets a tab, including the shared 401/403/429 — the
 * question "what does this answer when my signature is wrong" should be
 * answerable on the endpoint's own page, not by remembering that there is an
 * errors guide.
 */
export function ResponseTabs({ panels }: { panels: ResponsePanel[] }) {
  const [active, setActive] = useState(panels[0]?.status ?? "");
  const shown = panels.find((panel) => panel.status === active) ?? panels[0];

  return (
    <div>
      <div className="border-border flex flex-wrap gap-4 border-b">
        {panels.map((panel) => (
          <button
            key={panel.status}
            type="button"
            onClick={() => {
              setActive(panel.status);
            }}
            className={`-mb-px border-b-2 px-0.5 pb-2 font-mono text-[13px] font-semibold ${
              panel.status === shown?.status
                ? toneOf(panel.status)
                : "text-tx-dim border-transparent"
            }`}
          >
            {panel.status}
          </button>
        ))}
      </div>
      <div className="pt-4">
        {shown?.description !== undefined && (
          <Prose text={shown.description} className="text-tx-mute mb-4 text-[13.5px]" />
        )}
        {shown?.body}
      </div>
    </div>
  );
}
