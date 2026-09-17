import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { CodeTabs } from "@/components/docs/CodeTabs";
import { Code, DocsPage, Section, Table } from "@/components/docs/Page";
import { JsonLd } from "@/components/JsonLd";
import { routing } from "@/i18n/routing";
import { techArticle } from "@/lib/jsonld";
import { alternates, localeUrl } from "@/lib/seo";

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
    title: `${t("errorsTitle")} — YuPay Merchant API`,
    alternates: alternates(locale, "/docs/errors"),
  };
}

/**
 * The published error vocabulary.
 *
 * A hand-kept list, and deliberately so: these are the codes the module README
 * publishes as a contract, and the OpenAPI document declares the statuses but
 * not the per-code meanings. Keeping the table here rather than deriving it
 * means one page has to be edited when a code is added — which is the right
 * cost for a vocabulary a third party switches on.
 */
const SHARED: [string, string, string][] = [
  ["401", "missing_credentials", "One of the three headers is absent."],
  ["401", "stale_timestamp", "Not digits, or more than ±300 s from our clock."],
  ["401", "invalid_credentials", "Unknown key, revoked key, or a signature that does not match."],
  ["403", "merchant_frozen", "The account is suspended. Reads still work; writes do not."],
  ["403", "ip_not_allowed", "This address is not on the key's allowlist."],
  ["429", "—", "Rate limited. Read Retry-After and back off."],
  ["422", "invalid_request", "The body failed validation. `errors` carries the per-field detail."],
];

const ORDERS: [string, string, string][] = [
  ["404", "sku_not_found", "No such `sku_id`, or it is not visible to you."],
  ["404", "item_unavailable", "This SKU cannot be ordered right now. The body carries a `reason`."],
  [
    "409",
    "insufficient_deposit",
    "Body carries `balance_usd` and `required_usd`. Top up and retry the **same** id.",
  ],
  ["409", "order_id_reused", "This `merchant_order_id` already belongs to a different order."],
  ["422", "price_changed", "Drift beyond ±2%. Body carries `current_price`. Decide, then re-send."],
];

const SHAPE = `{
  "type": "https://app.yupay.uz/errors/conflict",
  "title": "Conflict",
  "status": 409,
  "detail": "not enough on the deposit for this order",
  "code": "insufficient_deposit",
  "balance_usd": "4.10",
  "required_usd": "16.54"
}`;

export default async function ErrorsPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("merchant.docs");

  const table = (rows: [string, string, string][]) => (
    <Table
      head={[t("colStatus"), t("colCode"), t("colWhen")]}
      rows={rows.map(([status, code, when]) => [
        <span key="s" className="font-mono font-semibold">
          {status}
        </span>,
        code === "—" ? (
          <span key="c" className="text-tx-dim">
            —
          </span>
        ) : (
          <Code key="c">{code}</Code>
        ),
        <span key="w">{when}</span>,
      ])}
    />
  );

  return (
    <>
      <JsonLd
        data={techArticle({
          headline: t("errorsTitle"),
          description: t("errorsLead"),
          url: localeUrl(locale, "/docs/errors"),
          dateModified: new Date().toISOString(),
        })}
      />
      <DocsPage eyebrow={t("groupStart")} title={t("errorsTitle")} lead={t("errorsLead")}>
        <Section id="shape" title={t("errorsShape")}>
          <CodeTabs
            copyLabel={t("copy")}
            copiedLabel={t("copied")}
            tabs={[{ id: "json", label: "JSON", code: SHAPE }]}
          />
        </Section>
        <Section id="shared" title={t("errorsShared")}>
          {table(SHARED)}
        </Section>
        <Section id="orders" title={t("errorsOrder")}>
          {table(ORDERS)}
        </Section>
      </DocsPage>
    </>
  );
}
