import { ArrowRight, ExternalLink } from "lucide-react";
import Link from "next/link";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { DocsPage, Section } from "@/components/docs/Page";
import { Prose } from "@/components/docs/Prose";
import { routing } from "@/i18n/routing";
import { contract, endpoints } from "@/lib/contract";

export const revalidate = 3600;

/** Both the schema and its Swagger UI are served by the API, beside each other. */
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export default async function IntroductionPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("merchant.docs");
  const doc = contract();

  return (
    <DocsPage title={t("introTitle")} lead={t("introLead")}>
      <Section id="what" title={t("introWhat")}>
        <p className="text-tx-mute text-[14px] leading-relaxed">{t("introWhatBody")}</p>
      </Section>

      <Section id="rules" title={t("introRules")}>
        <ol className="space-y-3">
          {["introRule1", "introRule2", "introRule3"].map((key, index) => (
            <li key={key} className="border-border bg-card flex gap-3.5 rounded-xl border p-4">
              <span className="text-primary shrink-0 font-mono text-[12px] font-bold">
                {String(index + 1).padStart(2, "0")}
              </span>
              <Prose text={t(key)} className="text-tx-mute min-w-0 text-[13.5px]" />
            </li>
          ))}
        </ol>
      </Section>

      <Section id="endpoints" title={t("groupSchemas") === "" ? "API" : "API"}>
        {/* Every operation, listed from the contract. A hand-kept list here
            would be the first thing to go stale, and this is the page that
            tells a reader how big the API is. */}
        <ul className="divide-border divide-y">
          {endpoints().map((endpoint) => (
            <li key={endpoint.id}>
              <Link
                href={`/${locale}/docs/api/${endpoint.id}`}
                className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-3"
              >
                <span className="text-tx-dim w-12 shrink-0 font-mono text-[11px] font-bold">
                  {endpoint.method}
                </span>
                <span className="text-[14px] font-medium">
                  {endpoint.operation.summary ?? endpoint.path}
                </span>
                <code className="text-tx-dim font-mono text-[12px]">{endpoint.path}</code>
              </Link>
            </li>
          ))}
        </ul>
      </Section>

      <Section id="next" title={t("introNext")}>
        <div className="flex flex-wrap gap-3">
          <Link
            href={`/${locale}/docs/quickstart`}
            className="bg-primary text-primary-foreground rounded-btn inline-flex items-center gap-2 px-4 py-2.5 text-sm font-semibold"
          >
            {t("quickTitle")}
            <ArrowRight size={15} />
          </Link>
          <Link
            href={`/${locale}/docs/authentication`}
            className="border-border rounded-btn inline-flex items-center px-4 py-2.5 text-sm font-semibold"
          >
            {t("authTitle")}
          </Link>
          {/* Swagger, not the raw schema. A reader who followed the old link
              got a wall of JSON in a browser tab; the one person who wants
              that — somebody feeding a client generator — finds it linked at
              the top of Swagger's own page. */}
          <a
            href={`${API_BASE}/merchant/docs`}
            className="border-border rounded-btn inline-flex items-center gap-2 px-4 py-2.5 text-sm font-semibold"
          >
            {t("fullReference")}
            <ExternalLink size={14} />
          </a>
        </div>
        <p className="text-tx-dim mt-1 text-[12.5px]">
          {t("fullReferenceHint")} · OpenAPI {doc.openapi}
        </p>
        <p className="text-tx-dim mt-1 text-[12.5px]">{t("swaggerUiHint")}</p>
      </Section>
    </DocsPage>
  );
}
