import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { CodeTabs } from "@/components/docs/CodeTabs";
import { Code, DocsPage, Section, Table } from "@/components/docs/Page";
import { Prose } from "@/components/docs/Prose";
import { JsonLd } from "@/components/JsonLd";
import { routing } from "@/i18n/routing";
import { apiBaseUrl } from "@/lib/contract";
import { techArticle } from "@/lib/jsonld";
import { LANGUAGES, sampleFor, signedSampleFor } from "@/lib/samples";
import { alternates, dayStamp, localeUrl, ROBOTS } from "@/lib/seo";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "merchant.docs" });
  return {
    title: `${t("authTitle")} — YuPay Merchant API`,
    alternates: alternates(locale, "/docs/authentication"),
    robots: ROBOTS,
  };
}

const CANONICAL = `{timestamp}
{METHOD}
{raw_path}
{raw_query}
{sha256_hex(body)}`;

export default async function AuthenticationPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("merchant.docs");

  const base = apiBaseUrl();

  // The GET that needs the least explaining — the one an integrator runs
  // first to prove the key works before any money is involved.
  const sample = {
    method: "GET",
    path: "/merchant/v1/me",
    query: "",
    body: null,
    baseUrl: base,
  };

  return (
    <>
      <JsonLd
        data={techArticle({
          headline: t("authTitle"),
          description: t("authLead"),
          url: localeUrl(locale, "/docs/authentication"),
          dateModified: dayStamp().toISOString(),
        })}
      />
      <DocsPage eyebrow={t("groupStart")} title={t("authTitle")} lead={t("authLead")}>
        <Section id="headers" title={t("authHeaders")}>
          <Table
            head={[t("colHeader"), t("colValue"), t("colDescription")]}
            rows={[
              [
                <Code key="h">Authorization</Code>,
                <span key="v" className="text-tx-dim font-mono text-xs">
                  Bearer ypk_…
                </span>,
                <span key="d">{t("authBearer")}</span>,
              ],
            ]}
          />
          <CodeTabs
            label={t("requestSample")}
            copyLabel={t("copy")}
            copiedLabel={t("copied")}
            tabs={LANGUAGES.map((language) => ({
              id: language.id,
              label: language.label,
              code: sampleFor(language.id, sample),
            }))}
          />
        </Section>

        <Section id="keys" title={t("authKeys")}>
          <Prose text={t("authKeysBody")} className="text-tx-mute text-sm" />
        </Section>

        {/* ADR-0103: keys issued before the single key keep the signed scheme,
            unchanged. Documented in full so an integration built on it can
            still be maintained, but below the fold — nobody new should start
            here. */}
        <Section id="legacy" title={t("authLegacy")}>
          <Prose text={t("authLegacyBody")} className="text-tx-mute text-sm" />
          <Table
            head={[t("colHeader"), t("colValue")]}
            rows={[
              [
                <Code key="h">X-Merchant-Key</Code>,
                <span key="v" className="text-tx-dim font-mono text-xs">
                  ypm_…
                </span>,
              ],
              [
                <Code key="h">X-Merchant-Timestamp</Code>,
                <span key="v" className="text-tx-dim font-mono text-xs">
                  1789454994
                </span>,
              ],
              [
                <Code key="h">X-Merchant-Signature</Code>,
                <span key="v" className="text-tx-dim font-mono text-xs">
                  hex
                </span>,
              ],
            ]}
          />
          <h3 className="mt-6 font-semibold">{t("authCanonical")}</h3>
          <Prose text={t("authCanonicalBody")} className="text-tx-mute text-sm" />
          <CodeTabs
            copyLabel={t("copy")}
            copiedLabel={t("copied")}
            tabs={[{ id: "canonical", label: "canonical", code: CANONICAL }]}
          />
          <CodeTabs
            label={t("requestSample")}
            copyLabel={t("copy")}
            copiedLabel={t("copied")}
            tabs={LANGUAGES.map((language) => ({
              id: language.id,
              label: language.label,
              code: signedSampleFor(language.id, sample),
            }))}
          />
          <h3 className="mt-6 font-semibold">{t("authWindow")}</h3>
          <Prose text={t("authWindowBody")} className="text-tx-mute text-sm" />
        </Section>

        {/* Both numbers are enforced on every call and neither was written
            down anywhere a merchant could read. An integrator sizing a nightly
            catalogue sync has to know the ceiling BEFORE they write the loop,
            not after a 429 they have no documented `Retry-After` for. */}
        <Section id="limits" title={t("authLimits")}>
          <Prose text={t("authLimitsBody")} className="text-tx-mute text-sm" />
        </Section>
      </DocsPage>
    </>
  );
}
