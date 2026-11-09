"use client";

import { ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import type { IpAllowlist } from "@/lib/types";

import { ApiError, api } from "@/lib/api";

function newKey(): string {
  return `cab-${crypto.randomUUID()}`;
}

/**
 * The merchant's API IP allowlist (ADR-0103): one list, every key, editable.
 *
 * It used to be fixed per key at issue, so adding a server's second address
 * (its IPv6, say) meant a new key and a redeploy. Now it is a textarea and a
 * Save button; the server validates every entry and says which one it refused.
 */
export function IpAllowlistCard() {
  const t = useTranslations("merchant.settings");

  const [text, setText] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api<IpAllowlist>("/api-ip-allowlist").then(
      (list) => {
        setText(list.entries.join("\n"));
        setLoaded(true);
      },
      () => {
        setLoaded(true);
      },
    );
  }, []);

  return (
    <section className="border-border bg-card mt-6 rounded-xl border p-6">
      <h2 className="flex items-center gap-2 font-semibold">
        <ShieldCheck size={17} />
        {t("ipTitle")}
      </h2>
      <p className="text-tx-mute mt-1.5 max-w-2xl text-sm leading-relaxed">{t("ipBody")}</p>

      <form
        className="mt-5"
        onSubmit={(event) => {
          event.preventDefault();
          setBusy(true);
          setSaved(false);
          setError(null);
          // Blank lines and stray spaces are the ordinary result of pasting a
          // list; the server skips them too, but the box should show what was kept.
          const entries = text
            .split("\n")
            .map((line) => line.trim())
            .filter((line) => line !== "");
          void api<IpAllowlist>("/api-ip-allowlist", {
            method: "PUT",
            body: { entries },
            idempotencyKey: newKey(),
          })
            .then((list) => {
              setText(list.entries.join("\n"));
              setSaved(true);
            })
            .catch((cause: unknown) => {
              setError(cause instanceof ApiError ? cause.message : t("ipError"));
            })
            .finally(() => {
              setBusy(false);
            });
        }}
      >
        <label htmlFor="api-ips" className="sr-only">
          {t("ipTitle")}
        </label>
        <textarea
          id="api-ips"
          rows={4}
          value={text}
          disabled={!loaded}
          placeholder={t("ipPlaceholder")}
          onChange={(event) => {
            setText(event.target.value);
            setSaved(false);
          }}
          className="border-border bg-card rounded-btn block w-full max-w-xl resize-y border px-3.5 py-3 font-mono text-xs"
        />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={busy || !loaded}
            className="bg-primary text-primary-foreground rounded-btn px-4 py-2.5 text-sm font-semibold disabled:opacity-60"
          >
            {t("save")}
          </button>
          {saved && <span className="text-tx-mute text-sm">{t("saved")}</span>}
        </div>
        {error !== null && <p className="text-danger mt-2 text-sm">{error}</p>}
      </form>
    </section>
  );
}
