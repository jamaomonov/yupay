"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

export interface Tab {
  id: string;
  label: string;
  code: string;
}

/**
 * A code block with tabs and a copy button.
 *
 * Deliberately unhighlighted. A syntax highlighter is 40–100 KB of JavaScript
 * on a page whose job is to be read, it has to be told a grammar per language,
 * and a wrong grammar colours a sample misleadingly — which is worse than one
 * colour. The mono face and the structure carry it.
 */
export function CodeTabs({
  tabs,
  label,
  copyLabel,
  copiedLabel,
}: {
  tabs: Tab[];
  label?: string;
  copyLabel: string;
  copiedLabel: string;
}) {
  const [active, setActive] = useState(tabs[0]?.id ?? "");
  const [copied, setCopied] = useState(false);
  const shown = tabs.find((tab) => tab.id === active) ?? tabs[0];

  return (
    <div className="border-border bg-card overflow-hidden rounded-xl border">
      <div className="border-border bg-card-2 flex items-center gap-1 border-b px-2 py-1.5">
        {label !== undefined && (
          <span className="text-tx-dim px-2 text-[11px] font-semibold tracking-wide">{label}</span>
        )}
        {tabs.length > 1 &&
          tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => {
                setActive(tab.id);
                setCopied(false);
              }}
              className={`rounded-btn px-2.5 py-1 text-[12px] ${
                tab.id === shown?.id ? "bg-card text-foreground font-semibold" : "text-tx-mute"
              }`}
            >
              {tab.label}
            </button>
          ))}
        <button
          type="button"
          aria-label={copied ? copiedLabel : copyLabel}
          onClick={() => {
            if (shown === undefined) return;
            void navigator.clipboard.writeText(shown.code).then(
              () => {
                setCopied(true);
                setTimeout(() => {
                  setCopied(false);
                }, 2000);
              },
              () => undefined,
            );
          }}
          className="text-tx-dim ml-auto inline-flex items-center gap-1.5 px-2 py-1 text-[11px]"
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? copiedLabel : copyLabel}
        </button>
      </div>
      <pre className="max-h-[32rem] overflow-auto p-4 font-mono text-[12.5px] leading-[1.7]">
        <code>{shown?.code ?? ""}</code>
      </pre>
    </div>
  );
}
