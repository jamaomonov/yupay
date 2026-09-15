import Link from "next/link";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { CodeTabs } from "@/components/docs/CodeTabs";
import { DocsPage, Section } from "@/components/docs/Page";
import { routing } from "@/i18n/routing";
import { apiBaseUrl, contract, endpoints } from "@/lib/contract";
import { bodySchema } from "@/lib/contract";
import { exampleJson } from "@/lib/example";
import { pathFor } from "@/lib/locale-href";
import { LANGUAGES, sampleFor } from "@/lib/samples";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export default async function QuickstartPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("merchant.docs");
  const base = apiBaseUrl();

  const order = endpoints().find((entry) => entry.id === "post-orders");
  const orderBody = bodySchema(order?.operation.requestBody?.content);

  // The four calls, in the order somebody actually makes them. Each sample is
  // generated from the same functions the reference uses, so a change to the
  // signing shows up here too rather than leaving a quick start that no longer
  // works — which is the page an integrator judges the whole API by.
  const steps = [
    { key: "step1", sample: null },
    {
      key: "step2",
      sample: { method: "GET", path: "/merchant/v1/me", query: "", body: null, baseUrl: base },
    },
    {
      key: "step3",
      sample: { method: "GET", path: "/merchant/v1/catalog", query: "", body: null, baseUrl: base },
    },
    {
      key: "step4",
      sample: {
        method: "POST",
        path: "/merchant/v1/orders",
        query: "",
        body: orderBody === undefined ? null : exampleJson(orderBody),
        baseUrl: base,
      },
    },
  ] as const;

  return (
    <DocsPage eyebrow={t("groupStart")} title={t("quickTitle")} lead={t("quickLead")}>
      {steps.map(({ key, sample }, index) => (
        <Section key={key} id={key} title={`${String(index + 1)}. ${t(`${key}Title`)}`}>
          <p className="text-tx-mute text-[14px] leading-relaxed">{t(`${key}Body`)}</p>
          {sample !== null && (
            <CodeTabs
              copyLabel={t("copy")}
              copiedLabel={t("copied")}
              tabs={LANGUAGES.map((language) => ({
                id: language.id,
                label: language.label,
                code: sampleFor(language.id, sample),
              }))}
            />
          )}
        </Section>
      ))}

      <Section id="then" title={t("introNext")}>
        <ul className="text-tx-mute ml-4 list-disc space-y-1.5 text-[14px]">
          <li>
            <Link
              href={pathFor(locale, "/docs/api/get-orders-merchant-order-id")}
              className="underline underline-offset-4"
            >
              {t("quickPoll")}
            </Link>
          </li>
          <li>
            <Link href={pathFor(locale, "/docs/webhooks")} className="underline underline-offset-4">
              {t("navWebhooks")}
            </Link>
          </li>
          <li>
            <Link href={pathFor(locale, "/docs/errors")} className="underline underline-offset-4">
              {t("navErrors")}
            </Link>
          </li>
        </ul>
      </Section>
    </DocsPage>
  );
}
