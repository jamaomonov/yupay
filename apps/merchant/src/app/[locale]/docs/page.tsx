import { getTranslations, setRequestLocale } from "next-intl/server";

export const revalidate = 3600;

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

/**
 * The quick start (spec §11).
 *
 * Deliberately short. The exhaustive reference is the OpenAPI schema and the
 * module README — duplicating either here would create a second document to
 * keep true, and the one that drifts is always the prose. What a reseller
 * cannot get from a schema is the *order* to do things in, which is this.
 */
export default async function DocsPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("merchant.docs");

  const steps = [t("step1"), t("step2"), t("step3")];
  const kinds = [t("kindFixed"), t("kindUnit"), t("kindAmount")];

  return (
    <main className="mx-auto w-full max-w-3xl px-5 py-16">
      <h1 className="text-3xl font-bold tracking-tight">{t("title")}</h1>
      <p className="text-tx-mute mt-3 leading-relaxed">{t("lead")}</p>

      <section className="mt-12">
        <h2 className="text-xl font-semibold tracking-tight">{t("quickstartTitle")}</h2>
        <ol className="mt-4 space-y-3">
          {steps.map((step, index) => (
            <li key={step} className="border-border bg-card rounded-xl border p-4">
              <span className="text-primary font-mono text-xs">
                {String(index + 1).padStart(2, "0")}
              </span>
              <p className="mt-1.5 text-sm leading-relaxed">{step}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="mt-12">
        <h2 className="text-xl font-semibold tracking-tight">{t("kindsTitle")}</h2>
        <ul className="text-tx-mute mt-4 space-y-2 text-sm leading-relaxed">
          {kinds.map((kind) => (
            <li key={kind} className="font-mono">
              {kind}
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-12">
        <h2 className="text-xl font-semibold tracking-tight">{t("webhooksTitle")}</h2>
        <p className="text-tx-mute mt-3 text-sm leading-relaxed">{t("webhooksBody")}</p>
      </section>

      <section className="mt-12">
        {/* The machine API's own schema, not the app's: `/openapi.json` carries
            every admin and storefront path we have, and a client generated
            from it would be a map of our whole surface. */}
        <a
          href={`${API_BASE}/merchant/v1/openapi.json`}
          className="border-border rounded-btn inline-flex border px-4 py-2.5 text-sm font-semibold"
        >
          {t("fullReference")}
        </a>
        <p className="text-tx-dim mt-2.5 text-sm">{t("fullReferenceHint")}</p>
      </section>
    </main>
  );
}
