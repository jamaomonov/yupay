import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";
import type { ReactNode } from "react";

import { CodeTabs } from "@/components/docs/CodeTabs";
import { Code, DocsPage, Section, Table } from "@/components/docs/Page";
import { JsonLd } from "@/components/JsonLd";
import { routing } from "@/i18n/routing";
import { techArticle } from "@/lib/jsonld";
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
    title: `${t("errorsTitle")} — YuPay Merchant API`,
    alternates: alternates(locale, "/docs/errors"),
    robots: ROBOTS,
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
 *
 * What lives here is the **structure** — status, wire code, catalogue key. The
 * prose moved to `merchant.docs.errCodes.*`, because it was English in all
 * three locales: a Russian-speaking integrator read a fully translated page
 * whose only two tables — the ones carrying the actual instructions — were not.
 * The third element is the catalogue key rather than the code itself so that
 * the one row with no code (`429`) can still have a message.
 */
const SHARED: [string, string, string][] = [
  ["401", "missing_credentials", "missing_credentials"],
  ["401", "stale_timestamp", "stale_timestamp"],
  ["401", "invalid_credentials", "invalid_credentials"],
  ["403", "merchant_frozen", "merchant_frozen"],
  ["403", "ip_not_allowed", "ip_not_allowed"],
  ["429", "—", "rate_limited"],
  ["422", "invalid_request", "invalid_request"],
];

// `sku_not_found` used to head this list and does not exist anywhere in the
// API — an unknown id answers `item_unavailable` with `reason: "unknown_sku"`.
// So `if (code === "sku_not_found")` was dead code in every integration that
// trusted this page, and "bad SKU id" fell silently into the generic bucket.
// Removed, along with the gaps beside it: the quantity/amount family and
// `margin_floor` are returned by `quote.py` and were on no public page.
const ORDERS: [string, string, string][] = [
  ["404", "item_unavailable", "item_unavailable"],
  ["404", "order_not_found", "order_not_found"],
  ["409", "insufficient_deposit", "insufficient_deposit"],
  ["409", "order_id_reused", "order_id_reused"],
  ["422", "price_changed", "price_changed"],
  ["422", "quantity_required", "quantity_required"],
  ["422", "quantity_not_accepted", "quantity_not_accepted"],
  ["422", "quantity_out_of_range", "quantity_out_of_range"],
  ["422", "amount_required", "amount_required"],
  ["422", "amount_not_accepted", "amount_not_accepted"],
  ["422", "amount_out_of_range", "amount_out_of_range"],
  ["422", "margin_floor", "margin_floor"],
];

// The `reason` on `item_unavailable`. The page told a reader to read this
// field and never said what it can hold, so the one thing they were pointed
// at was the one thing they could not branch on.
//
// Seven values, not the six the order path can produce: `validate/player`
// shares the code and the vocabulary (`quote.unavailable_brand`) and answers
// `unknown_brand`, echoing `brand` where the order path echoes `sku_id`.
const UNAVAILABLE_REASONS = [
  "unknown_sku",
  "unknown_brand",
  "not_b2b_visible",
  "out_of_stock",
  "not_for_sale",
  "no_cost",
  "variable_amount",
] as const;

const SHAPE = `{
  "type": "https://app.yupay.uz/errors/conflict",
  "title": "Conflict",
  "status": 409,
  "detail": "not enough on the deposit for this order",
  "code": "insufficient_deposit",
  "balance_usd": "4.10",
  "required_usd": "16.54"
}`;

/**
 * The `when` column carries `\`code\`` and `**emphasis**`, and was rendered as
 * a plain string — so the page literally showed backticks and asterisks to
 * every reader, in all three locales. This is not a markdown parser: two
 * markers, on our own strings, is the whole requirement, and a parser here
 * would be a dependency and an XSS surface for a dozen table cells.
 */
function inline(text: string): ReactNode[] {
  return text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).map((part, i) => {
    if (part.startsWith("`") && part.endsWith("`") && part.length > 1) {
      return <Code key={i}>{part.slice(1, -1)}</Code>;
    }
    if (part.startsWith("**") && part.endsWith("**") && part.length > 3) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    return <span key={i}>{part}</span>;
  });
}

export default async function ErrorsPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("merchant.docs");

  const table = (rows: [string, string, string][]) => (
    <Table
      head={[t("colStatus"), t("colCode"), t("colWhen")]}
      rows={rows.map(([status, code, key]) => [
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
        <span key="w">{inline(t(`errCodes.${key}`))}</span>,
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
          dateModified: dayStamp().toISOString(),
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
        <Section id="reasons" title={t("errorsReasons")}>
          <Table
            head={[t("colReason"), t("colMeaning")]}
            rows={UNAVAILABLE_REASONS.map((reason) => [
              <Code key="r">{reason}</Code>,
              <span key="m">{inline(t(`errReasons.${reason}`))}</span>,
            ])}
          />
        </Section>
      </DocsPage>
    </>
  );
}
