"use client";

import { KeyRound } from "lucide-react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import type { ApiKey, IssuedKey } from "@/lib/types";

import { CopyButton } from "@/components/CopyButton";
import { api } from "@/lib/api";
import { formatMoment } from "@/lib/datetime";

/** A `ypk_` key is one value (ADR-0103); older keys are an id + a signing secret. */
const SINGLE_KEY_PREFIX = "ypk_";

/**
 * Machine credentials: issue, list, revoke.
 *
 * A new key is ONE string, `ypk_…`, sent as `Authorization: Bearer`. It used
 * to be three — key id, signing secret and webhook secret, all starting `ypm`
 * — and a real integration once put every one of them in the wrong slot. The
 * IP allowlist is no longer per key: it is the merchant's, in its own card.
 */
export function ApiKeysCard() {
  const t = useTranslations("merchant.settings");
  const { locale } = useParams<{ locale: string }>();

  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [label, setLabel] = useState("");
  const [issued, setIssued] = useState<IssuedKey | null>(null);
  // The key_id awaiting a second click. Revoking is one-way and instant —
  // a live integration stops the moment it lands — so it asks first, inline
  // rather than through `confirm()`, which a browser may suppress entirely.
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api<ApiKey[]>("/api-keys").then(setKeys, () => {
      setKeys([]);
    });
  }, []);

  return (
    <section className="border-border bg-card mt-6 rounded-xl border p-6">
      <h2 className="flex items-center gap-2 font-semibold">
        <KeyRound size={17} />
        {t("keysTitle")}
      </h2>
      <p className="text-tx-mute mt-1.5 text-sm leading-relaxed">{t("keysBody")}</p>

      {issued !== null && (
        // Rendered above the list and never re-rendered from it: this is the
        // only moment the key exists outside our encryption, so the panel has
        // to be impossible to miss and impossible to get back.
        <div
          role="status"
          translate="no"
          className="border-primary bg-card-2 mt-5 rounded-xl border p-5"
        >
          <p className="font-semibold">{t("secretOnceTitle")}</p>
          <p className="text-tx-mute mt-1.5 text-sm leading-relaxed">{t("secretOnceBody")}</p>

          <p className="mt-4 break-all font-mono text-sm">{issued.api_key}</p>
          <p className="text-tx-dim mt-1 max-w-xl text-xs leading-relaxed">{t("apiKeyHint")}</p>
          <div className="mt-2">
            <CopyButton value={issued.api_key} label={t("copyApiKey")} done={t("copied")} />
          </div>

          {/* The panel used to sit there until something else re-rendered the
              page, so the way it left was a reload — which is the one event
              that loses the key without asking. Dismissing it is now a
              deliberate click that says what it means. */}
          <button
            type="button"
            onClick={() => {
              setIssued(null);
            }}
            className="border-border rounded-btn mt-5 border px-4 py-2 text-sm font-semibold"
          >
            {t("savedIt")}
          </button>
        </div>
      )}

      <form
        className="mt-5 flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          setBusy(true);
          void api<IssuedKey>("/api-keys", { method: "POST", body: { label } })
            .then((key) => {
              setIssued(key);
              setLabel("");
              return api<ApiKey[]>("/api-keys").then(setKeys);
            })
            .catch(() => undefined)
            .finally(() => {
              setBusy(false);
            });
        }}
      >
        <div className="min-w-0 basis-full sm:max-w-xs sm:flex-1 sm:basis-auto">
          <label htmlFor="key-label" className="text-tx-mute mb-1.5 block text-sm">
            {t("label")}
          </label>
          <input
            id="key-label"
            value={label}
            maxLength={64}
            placeholder={t("labelHint")}
            onChange={(event) => {
              setLabel(event.target.value);
            }}
            className="border-border bg-card rounded-btn h-11 w-full border px-3.5 text-sm"
          />
        </div>
        <button
          type="submit"
          disabled={busy}
          className="bg-primary text-primary-foreground rounded-btn h-11 px-4 text-sm font-semibold disabled:opacity-60"
        >
          {t("createKey")}
        </button>
      </form>

      {keys !== null && keys.length === 0 && (
        <p className="text-tx-dim mt-5 text-sm">{t("noKeys")}</p>
      )}

      {keys !== null && keys.length > 0 && (
        <ul className="border-border divide-border mt-5 divide-y border-t">
          {keys.map((key) => {
            const single = key.key_id.startsWith(SINGLE_KEY_PREFIX);
            return (
              <li key={key.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3.5">
                <div className="min-w-0 flex-1">
                  {/* A `ypk_` key shows only its start: enough to recognise it,
                      and never mistaken for the whole key. An older key's id
                      still goes in `X-Merchant-Key`, so it keeps its copy button. */}
                  <div className="flex items-center gap-2">
                    <p className="min-w-0 break-all font-mono text-xs">
                      {single ? `${key.key_id.slice(0, 12)}…` : key.key_id}
                    </p>
                    {!single && (
                      <CopyButton value={key.key_id} label={t("copy")} done={t("copied")} />
                    )}
                  </div>
                  <p className="text-tx-dim mt-0.5 text-xs">
                    {key.label || "—"} · {t("lastUsed")}:{" "}
                    {key.last_used_at === null
                      ? t("never")
                      : formatMoment(key.last_used_at, locale)}
                    {!single && <> · {t("legacyKey")}</>}
                  </p>
                </div>
                {key.revoked_at !== null && (
                  <span className="text-tx-dim text-xs">{t("revoked")}</span>
                )}
                {key.revoked_at === null && confirming !== key.key_id && (
                  <button
                    type="button"
                    onClick={() => {
                      setConfirming(key.key_id);
                    }}
                    className="border-border text-danger rounded-btn border px-3 py-1.5 text-xs"
                  >
                    {t("revoke")}
                  </button>
                )}
                {key.revoked_at === null && confirming === key.key_id && (
                  <div translate="no" className="flex flex-wrap items-center gap-2">
                    <p className="text-tx-mute w-full text-xs">{t("revokeConfirm")}</p>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        setBusy(true);
                        void api<ApiKey>(`/api-keys/${encodeURIComponent(key.key_id)}`, {
                          method: "DELETE",
                        })
                          .then(() => api<ApiKey[]>("/api-keys").then(setKeys))
                          .catch(() => undefined)
                          .finally(() => {
                            setConfirming(null);
                            setBusy(false);
                          });
                      }}
                      className="bg-danger rounded-btn px-3 py-1.5 text-xs font-semibold text-[hsl(var(--bg))] disabled:opacity-50"
                    >
                      {t("revokeYes")}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setConfirming(null);
                      }}
                      className="border-border text-tx-mute rounded-btn border px-3 py-1.5 text-xs"
                    >
                      {t("cancel")}
                    </button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
