"use client";

import { Settings } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import type { Profile } from "@/lib/types";

import { ApiKeysCard } from "@/components/ApiKeysCard";
import { useCabinet } from "@/components/CabinetContext";
import { PageHeading } from "@/components/PageHeading";
import { WebhookCard } from "@/components/WebhookCard";
import { api } from "@/lib/api";
import { formatMoment } from "@/lib/datetime";
import { pathFor } from "@/lib/locale-href";

/**
 * The zones a reseller in our markets actually sits in, plus UTC.
 *
 * A convenience list, not a constraint: the API accepts any IANA name the
 * running system can load, and a saved value outside this list is kept and
 * shown rather than replaced.
 */
const ZONES = [
  "Asia/Tashkent",
  "Asia/Almaty",
  "Asia/Bishkek",
  "Asia/Dushanbe",
  "Asia/Baku",
  "Asia/Dubai",
  "Europe/Moscow",
  "Europe/Kyiv",
  "Europe/London",
  "UTC",
];

export default function SettingsPage() {
  const t = useTranslations("merchant.settings");
  const tOffer = useTranslations("merchant.offer");
  const { locale } = useParams<{ locale: string }>();

  // From the shell rather than a fetch of its own — the top bar already has
  // it, and two reads of the same profile can disagree after a save.
  const { profile, refreshProfile } = useCabinet();
  const [zone, setZone] = useState("");
  const [savedZone, setSavedZone] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (profile !== null) setZone(profile.timezone);
  }, [profile]);

  return (
    <div>
      <PageHeading icon={Settings} title={t("title")} />

      <ApiKeysCard />

      <WebhookCard locale={locale} />

      <section className="border-border bg-card mt-6 rounded-xl border p-6">
        <h2 className="font-semibold">{t("timezoneTitle")}</h2>
        <p className="text-tx-mute mt-1.5 max-w-2xl text-sm leading-relaxed">{t("timezoneBody")}</p>
        <form
          className="mt-4 flex flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            setBusy(true);
            setSavedZone(false);
            void api<Profile>("/me", { method: "PATCH", body: { timezone: zone } })
              .then(() => {
                refreshProfile();
                setSavedZone(true);
              })
              .catch(() => undefined)
              .finally(() => {
                setBusy(false);
              });
          }}
        >
          <div>
            <label htmlFor="tz" className="text-tx-mute mb-1.5 block text-sm">
              {t("timezone")}
            </label>
            <select
              id="tz"
              value={zone}
              onChange={(event) => {
                setZone(event.target.value);
                setSavedZone(false);
              }}
              className="border-border bg-card rounded-btn w-56 border px-3.5 py-2.5 text-sm"
            >
              {/* The saved value first, so a zone set elsewhere — or one this
                  list has not heard of — is never silently replaced by the
                  first option the moment somebody presses Save. */}
              {(ZONES.includes(zone) ? ZONES : [zone, ...ZONES]).map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>
          <button
            type="submit"
            disabled={busy}
            className="border-border rounded-btn border px-4 py-2.5 text-sm font-semibold disabled:opacity-60"
          >
            {t("save")}
          </button>
          {savedZone && (
            <p role="status" className="text-tx-mute text-sm">
              {t("saved")}
            </p>
          )}
        </form>
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
          href={pathFor(locale, "/offer")}
          className="border-border rounded-btn mt-4 inline-flex border px-4 py-2 text-sm font-semibold"
        >
          {tOffer("title")}
        </Link>
      </section>
    </div>
  );
}
