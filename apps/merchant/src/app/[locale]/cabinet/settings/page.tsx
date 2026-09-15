"use client";

import { KeyRound } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import type { ApiKey, IssuedKey, Profile } from "@/lib/types";

import { CopyButton } from "@/components/CopyButton";
import { api } from "@/lib/api";
import { formatMoment } from "@/lib/datetime";

export default function SettingsPage() {
  const t = useTranslations("merchant.settings");
  const tOffer = useTranslations("merchant.offer");
  const { locale } = useParams<{ locale: string }>();

  const [profile, setProfile] = useState<Profile | null>(null);
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [label, setLabel] = useState("");
  const [issued, setIssued] = useState<IssuedKey | null>(null);
  // The key_id awaiting a second click. Revoking is one-way and instant —
  // a live integration stops the moment it lands — so it asks first, inline
  // rather than through `confirm()`, which a browser may suppress entirely.
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api<Profile>("/me").then(setProfile, () => undefined);
    void api<ApiKey[]>("/api-keys").then(setKeys, () => {
      setKeys([]);
    });
  }, []);

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>

      <section className="border-border bg-card mt-6 rounded-xl border p-6">
        <h2 className="flex items-center gap-2 font-semibold">
          <KeyRound size={17} />
          {t("keysTitle")}
        </h2>
        <p className="text-tx-mute mt-1.5 text-sm leading-relaxed">{t("keysBody")}</p>

        {issued !== null && (
          // Rendered above the list and never re-rendered from it: this is the
          // only moment the secret exists outside our encryption, so the panel
          // has to be impossible to miss and impossible to get back.
          <div className="border-primary bg-card-2 mt-5 rounded-xl border p-5">
            <p className="font-semibold">{t("secretOnceTitle")}</p>
            <p className="text-tx-mute mt-1.5 text-sm leading-relaxed">{t("secretOnceBody")}</p>
            <p className="mt-4 break-all font-mono text-xs">{issued.key_id}</p>
            <p className="mt-1.5 break-all font-mono text-sm">{issued.secret}</p>
            <div className="mt-3">
              <CopyButton value={issued.secret} label={t("copy")} done={t("copied")} />
            </div>
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
          <div>
            <label htmlFor="key-label" className="text-tx-mute mb-1.5 block text-sm">
              {t("label")}
            </label>
            <input
              id="key-label"
              value={label}
              maxLength={64}
              onChange={(event) => {
                setLabel(event.target.value);
              }}
              className="border-border bg-card rounded-btn w-56 border px-3.5 py-2.5 text-sm outline-none"
            />
          </div>
          <button
            type="submit"
            disabled={busy}
            className="bg-primary text-primary-foreground rounded-btn px-4 py-2.5 text-sm font-semibold disabled:opacity-60"
          >
            {t("createKey")}
          </button>
          <p className="text-tx-dim w-full text-xs">{t("labelHint")}</p>
        </form>

        {keys !== null && keys.length === 0 && (
          <p className="text-tx-dim mt-5 text-sm">{t("noKeys")}</p>
        )}

        {keys !== null && keys.length > 0 && (
          <ul className="border-border divide-border mt-5 divide-y border-t">
            {keys.map((key) => (
              <li key={key.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3.5">
                <div className="min-w-0 flex-1">
                  <p className="break-all font-mono text-xs">{key.key_id}</p>
                  <p className="text-tx-dim mt-0.5 text-xs">
                    {key.label || "—"} · {t("lastUsed")}:{" "}
                    {key.last_used_at === null
                      ? t("never")
                      : formatMoment(key.last_used_at, locale)}
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
                  <div className="flex flex-wrap items-center gap-2">
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
                      className="bg-danger rounded-btn px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
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
            ))}
          </ul>
        )}
      </section>

      <section className="border-border bg-card mt-6 rounded-xl border p-6">
        <h2 className="font-semibold">{t("offerTitle")}</h2>
        {profile?.offer_accepted_at != null && profile.offer_version != null && (
          <p className="text-tx-mute mt-1.5 text-sm">
            {t("offerAccepted", {
              date: formatMoment(profile.offer_accepted_at, locale),
              version: profile.offer_version,
            })}
          </p>
        )}
        <Link
          href={`/${locale}/offer`}
          className="border-border rounded-btn mt-4 inline-flex px-4 py-2 text-sm font-semibold"
        >
          {tOffer("title")}
        </Link>
      </section>
    </div>
  );
}
