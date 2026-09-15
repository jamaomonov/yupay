import { getTranslations, setRequestLocale } from "next-intl/server";

import { CodeTabs } from "@/components/docs/CodeTabs";
import { Code, DocsPage, Section, Table } from "@/components/docs/Page";
import { Prose } from "@/components/docs/Prose";
import { routing } from "@/i18n/routing";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

/**
 * The verification snippets.
 *
 * Copied from the module README, where `test_merchant_webhook_snippet.py`
 * **executes** them against the real signing helpers — so the code on this
 * page is code that is proven to verify a real delivery, not code that looks
 * like it should.
 */
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
    <DocsPage eyebrow={t("groupStart")} title={t("webhooksTitle")} lead={t("webhooksLead")}>
      <Section id="headers" title={t("authHeaders")}>
        <Table
          head={[t("colHeader"), t("colDescription")]}
          rows={[
            [<Code key="h">X-Yupay-Timestamp</Code>, <span key="d">Unix seconds, as sent.</span>],
            [
              <Code key="h">X-Yupay-Delivery</Code>,
              <span key="d">
                Stable across every retry of the same event. Dedupe on this — delivery is
                at-least-once.
              </span>,
            ],
            [<Code key="h">X-Yupay-Event</Code>, <span key="d">The event type.</span>],
            [
              <Code key="h">X-Yupay-Signature</Code>,
              <span key="d">Lowercase hex HMAC-SHA256 of the four fields below.</span>,
            ],
          ]}
        />
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
  );
}
