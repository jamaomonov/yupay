import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { CodeTabs } from "@/components/docs/CodeTabs";
import { Code, DocsPage, Section, Table } from "@/components/docs/Page";
import { Prose } from "@/components/docs/Prose";
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
    title: `${t("webhooksTitle")} — YuPay Merchant API`,
    alternates: alternates(locale, "/docs/webhooks"),
    robots: ROBOTS,
  };
}

/**
 * The verification snippets.
 *
 * Copied from the module README, where `test_merchant_webhook_snippet.py`
 * **executes** them against the real signing helpers — so the code on this
 * page is code that is proven to verify a real delivery, not code that looks
 * like it should.
 */
/** The four headers on every delivery, paired with their catalogue key. */
const HEADERS: [string, string][] = [
  ["X-Yupay-Timestamp", "hdrTimestamp"],
  ["X-Yupay-Delivery", "hdrDelivery"],
  ["X-Yupay-Event", "hdrEvent"],
  ["X-Yupay-Signature", "hdrSignature"],
];

/** The complete v1 event vocabulary — `webhooks.EVENT_TYPES`. */
const EVENTS: [string, string][] = [
  ["order.status_changed", "evOrderStatus"],
  ["balance.credited", "evBalanceCredited"],
  ["webhook.test", "evTest"],
];

const PYTHON = `import hashlib, hmac, time

SECRET = "ypmw_…"  # the webhook secret — a different credential from ypms_
TOLERANCE_SECONDS = 300


def verify(headers: dict[str, str], body: bytes) -> bool:
    ts = headers.get("X-Yupay-Timestamp", "")
    canonical = "\\n".join(
        (
            ts,
            headers.get("X-Yupay-Delivery", ""),
            headers.get("X-Yupay-Event", ""),
            hashlib.sha256(body).hexdigest(),
        )
    ).encode()
    expected = hmac.new(SECRET.encode(), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, headers.get("X-Yupay-Signature", "")):
        return False
    # Your own replay window; we do not impose one on you.
    return ts.isdigit() and abs(time.time() - int(ts)) <= TOLERANCE_SECONDS`;

const NODE = `import { createHash, createHmac, timingSafeEqual } from "node:crypto";

const SECRET = "ypmw_…";
const TOLERANCE_SECONDS = 300;

function verify(headers, body /* Buffer */) {
  const ts = headers["x-yupay-timestamp"] ?? "";
  const canonical = [
    ts,
    headers["x-yupay-delivery"] ?? "",
    headers["x-yupay-event"] ?? "",
    createHash("sha256").update(body).digest("hex"),
  ].join("\\n");
  const expected = createHmac("sha256", SECRET).update(canonical).digest("hex");
  const got = headers["x-yupay-signature"] ?? "";
  if (expected.length !== got.length) return false;
  if (!timingSafeEqual(Buffer.from(expected), Buffer.from(got))) return false;
  return /^\\d+$/.test(ts) && Math.abs(Date.now() / 1000 - Number(ts)) <= TOLERANCE_SECONDS;
}`;

export default async function WebhooksPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("merchant.docs");

  return (
    <>
      <JsonLd
        data={techArticle({
          headline: t("webhooksTitle"),
          description: t("webhooksLead"),
          url: localeUrl(locale, "/docs/webhooks"),
          dateModified: dayStamp().toISOString(),
        })}
      />
      <DocsPage eyebrow={t("groupStart")} title={t("webhooksTitle")} lead={t("webhooksLead")}>
        <Section id="headers" title={t("authHeaders")}>
          <Table
            head={[t("colHeader"), t("colDescription")]}
            rows={HEADERS.map(([name, key]) => [
              <Code key="h">{name}</Code>,
              <Prose key="d" text={t(key)} />,
            ])}
          />
        </Section>

        {/* The vocabulary a receiver switches on. The page described how to
            verify a delivery and never said what could arrive in one, so the
            `event_type` a reader was told to branch on was the one thing they
            could not enumerate — and `balance.debited`, which people assume
            exists because a debit is a thing that happens, is named here as
            absent rather than left to be discovered from a missing webhook. */}
        <Section id="events" title={t("webhooksEvents")}>
          <Table
            head={[t("colEvent"), t("colPayload")]}
            rows={EVENTS.map(([name, key]) => [
              <Code key="e">{name}</Code>,
              <Prose key="p" text={t(key)} />,
            ])}
          />
        </Section>

        <Section id="delivery" title={t("webhooksDelivery")}>
          <Prose text={t("webhooksDeliveryBody")} className="text-tx-mute text-sm" />
        </Section>

        {/* Every number here is a constant somebody has to plan around — a
            receiver that holds a request for 12 seconds is a receiver we
            never see succeed — and none of them were written down anywhere a
            merchant could read. */}
        <Section id="retries" title={t("webhooksRetries")}>
          <Prose text={t("webhooksRetriesBody")} className="text-tx-mute text-sm" />
        </Section>

        <Section id="verify" title={t("webhooksVerify")}>
          <Prose text={t("webhooksVerifyBody")} className="text-tx-mute text-sm" />
          <CodeTabs
            copyLabel={t("copy")}
            copiedLabel={t("copied")}
            tabs={[
              { id: "python", label: "Python", code: PYTHON },
              { id: "node", label: "Node.js", code: NODE },
            ]}
          />
        </Section>

        <Section id="no-code" title={t("webhooksNoCode")}>
          <Prose text={t("webhooksNoCodeBody")} className="text-tx-mute text-sm" />
        </Section>
      </DocsPage>
    </>
  );
}
