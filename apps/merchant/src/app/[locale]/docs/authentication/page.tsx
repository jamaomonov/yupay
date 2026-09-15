import { getTranslations, setRequestLocale } from "next-intl/server";

import { CodeTabs } from "@/components/docs/CodeTabs";
import { Code, DocsPage, Section, Table } from "@/components/docs/Page";
import { Prose } from "@/components/docs/Prose";
import { routing } from "@/i18n/routing";
import { apiBaseUrl, contract } from "@/lib/contract";
import { LANGUAGES, sampleFor } from "@/lib/samples";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
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

  const schemes = contract().components.securitySchemes ?? {};
  const base = apiBaseUrl();

  // The signed GET that needs the least explaining — the one an integrator
  // runs first to prove their signing works before any money is involved.
  const sample = {
    method: "GET",
    path: "/merchant/v1/me",
    query: "",
    body: null,
    baseUrl: base,
  };

  return (
    <DocsPage eyebrow={t("groupStart")} title={t("authTitle")} lead={t("authLead")}>
      <Section id="headers" title={t("authHeaders")}>
        <Table
          head={[t("colHeader"), t("colValue"), t("colDescription")]}
          rows={[
            ...Object.values(schemes).map((scheme) => [
              <Code key="h">{scheme.name ?? ""}</Code>,
              <span key="v" className="text-tx-dim font-mono text-[12px]">
                {scheme.name === "X-Merchant-Key" ? "ypm_…" : "hex"}
              </span>,
              <Prose key="d" text={scheme.description ?? ""} lang="en" />,
            ]),
            [
              <Code key="h">X-Merchant-Timestamp</Code>,
              <span key="v" className="text-tx-dim font-mono text-[12px]">
                1789454994
              </span>,
              <span key="d">Unix seconds, digits only. ±300 s of ours.</span>,
            ],
          ]}
        />
      </Section>

      <Section id="canonical" title={t("authCanonical")}>
        <Prose text={t("authCanonicalBody")} className="text-tx-mute text-[14px]" />
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
            code: sampleFor(language.id, sample),
          }))}
        />
      </Section>

      <Section id="window" title={t("authWindow")}>
        <Prose text={t("authWindowBody")} className="text-tx-mute text-[14px]" />
      </Section>

      <Section id="keys" title={t("authKeys")}>
        <Prose text={t("authKeysBody")} className="text-tx-mute text-[14px]" />
      </Section>
    </DocsPage>
  );
}
