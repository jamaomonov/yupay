"use client";

import { Braces, Check, Code, Copy, Terminal, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { CodeWindow } from "@/components/CodeWindow";

export interface Tab {
  id: string;
  label: string;
  code: string;
}

/**
 * What kind of thing the open tab is, as an icon.
 *
 * Keyed on the tab id the call sites already use — `curl`, `python`, `node`,
 * `json`. An id we have no icon for gets none rather than a wrong one: a
 * generic glyph beside every block is decoration, and the point of this one
 * is to distinguish "paste this in a terminal" from "this is a payload".
 */
const ICON_BY_TAB: Record<string, LucideIcon> = {
  curl: Terminal,
  python: Code,
  node: Code,
  json: Braces,
};

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
  const codeRegionLabel = useTranslations("merchant.common")("codeSample");
  const [active, setActive] = useState(tabs[0]?.id ?? "");
  const [copied, setCopied] = useState(false);
  const shown = tabs.find((tab) => tab.id === active) ?? tabs[0];

  return (
    <CodeWindow
      {...(shown === undefined ? {} : { icon: ICON_BY_TAB[shown.id] })}
      {...(label === undefined ? {} : { title: label })}
      actions={
        <>
          {tabs.length > 1 &&
            tabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                aria-pressed={tab.id === shown?.id}
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
            className="text-tx-dim inline-flex items-center gap-1.5 px-2 py-1 text-[11px]"
          >
            {copied ? <Check size={12} /> : <Copy size={12} />}
            {copied ? copiedLabel : copyLabel}
          </button>
        </>
      }
    >
      {/* Focusable, because it scrolls. Measured before this: 1420px of cURL
          inside a 356px box with `tabIndex: -1` and no focusable descendant,
          so a keyboard user could read the left quarter of our own
          integration sample and no more. A named region, not a bare stop. */}
      <pre
        tabIndex={0}
        role="region"
        aria-label={`${label ?? ""} ${shown?.label ?? ""}`.trim() || codeRegionLabel}
        className="max-h-[32rem] overflow-auto p-4 font-mono text-[12.5px] leading-[1.7]"
      >
        <code>{shown?.code ?? ""}</code>
      </pre>
    </CodeWindow>
  );
}
