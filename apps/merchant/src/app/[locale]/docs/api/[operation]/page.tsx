import { notFound } from "next/navigation";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { ResponsePanel } from "@/components/docs/ResponseTabs";
import type { Parameter } from "@/lib/contract";
import type { Metadata } from "next";

import { CodeTabs } from "@/components/docs/CodeTabs";
import { Prose } from "@/components/docs/Prose";
import { ResponseTabs } from "@/components/docs/ResponseTabs";
import { SchemaTable } from "@/components/docs/SchemaTable";
import { JsonLd } from "@/components/JsonLd";
import { routing } from "@/i18n/routing";
import { apiBaseUrl, bodySchema, contract, endpoints, typeLabel } from "@/lib/contract";
import { exampleJson } from "@/lib/example";
import { techArticle } from "@/lib/jsonld";
import { LANGUAGES, canonicalString, sampleFor } from "@/lib/samples";
import { alternates, localeUrl } from "@/lib/seo";

export const dynamicParams = false;

export function generateStaticParams() {
  // Every locale × every operation, prerendered: the reference is the page a
  // search engine should be able to read, and there is nothing dynamic in it.
  return routing.locales.flatMap((locale) =>
    endpoints().map((endpoint) => ({ locale, operation: endpoint.id })),
  );
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; operation: string }>;
}): Promise<Metadata> {
  const { locale, operation: slug } = await params;
  const endpoint = endpoints().find((entry) => entry.id === slug);
  if (endpoint === undefined) return {};
  const title = endpoint.operation.summary ?? endpoint.path;
  return {
    title: `${title} — YuPay Merchant API`,
    alternates: alternates(locale, `/docs/api/${slug}`),
  };
}

const METHOD_TONE: Record<string, string> = {
  GET: "bg-blue/10 text-blue",
  POST: "bg-primary/10 text-primary-ink",
  PUT: "bg-gold/10 text-gold",
  PATCH: "bg-gold/10 text-gold",
  DELETE: "bg-danger/10 text-danger",
};

/** Fill a path's `{placeholders}` with something that looks like a real value. */
function examplePath(path: string): string {
  return path
    .replaceAll(/\{merchant_order_id\}/g, "shop-10482")
    .replaceAll(/\{[^}]+\}/g, "example");
}

export default async function OperationPage({
  params,
}: {
  params: Promise<{ locale: string; operation: string }>;
}) {
  const { locale, operation: slug } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("merchant.docs");

  const endpoint = endpoints().find((entry) => entry.id === slug);
  if (endpoint === undefined) notFound();
  const { method, path, operation } = endpoint;

  const parameters = operation.parameters ?? [];
  const query = parameters.filter((p) => p.in === "query");
  const inPath = parameters.filter((p) => p.in === "path");
  const request = bodySchema(operation.requestBody?.content);
  const base = apiBaseUrl();

  const sample = {
    method,
    path: examplePath(path),
    query: query.length > 0 ? `${query[0]?.name ?? ""}=` : "",
    body: request === undefined ? null : exampleJson(request),
    baseUrl: base,
  };

  const panels: ResponsePanel[] = Object.entries(operation.responses).map(([status, response]) => {
    const schema = bodySchema(response.content);
    return {
      status,
      description: response.description,
      body:
        schema === undefined ? null : (
          <div className="space-y-5">
            <SchemaTable node={schema} locale={locale} />
            <CodeTabs
              label={t("exampleResponse")}
              copyLabel={t("copy")}
              copiedLabel={t("copied")}
              tabs={[{ id: "json", label: "JSON", code: exampleJson(schema) }]}
            />
          </div>
        ),
    };
  });

  return (
    <div className="mx-auto grid w-full max-w-[1400px] gap-10 px-4 py-8 sm:px-8 lg:grid-cols-[minmax(0,1fr)_28rem]">
      <JsonLd
        data={techArticle({
          headline: operation.summary ?? path,
          ...(operation.description !== undefined ? { description: operation.description } : {}),
          url: localeUrl(locale, `/docs/api/${slug}`),
          dateModified: new Date().toISOString(),
        })}
      />
      <article className="min-w-0">
        <h1 className="font-display text-2xl font-semibold tracking-tight sm:text-3xl">
          <span lang="en">{operation.summary ?? path}</span>
        </h1>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span
            className={`rounded-btn px-2.5 py-1 font-mono text-[11.5px] font-bold ${
              METHOD_TONE[method] ?? "bg-card-2 text-tx-mute"
            }`}
          >
            {method}
          </span>
          <code className="text-tx-mute break-all font-mono text-[13px]">{path}</code>
          {operation.security !== undefined && (
            <span className="bg-card-2 text-tx-mute rounded-btn px-2.5 py-1 text-[11.5px] font-semibold">
              {t("signedRequest")}
            </span>
          )}
        </div>

        {operation.description !== undefined && (
          <Prose text={operation.description} className="text-tx-mute mt-5 max-w-2xl" lang="en" />
        )}

        {(inPath.length > 0 || query.length > 0) && (
          <section className="mt-10">
            <h2 id="parameters" className="border-border border-b pb-2 text-lg font-semibold">
              {t("parameters")}
            </h2>
            {inPath.length > 0 && <ParameterList title={t("pathParams")} items={inPath} />}
            {query.length > 0 && <ParameterList title={t("queryParams")} items={query} />}
          </section>
        )}

        {request !== undefined && (
          <section className="mt-10">
            <h2 id="request" className="border-border border-b pb-2 text-lg font-semibold">
              {t("requestBody")}
            </h2>
            <div className="mt-4">
              <SchemaTable node={request} locale={locale} />
            </div>
          </section>
        )}

        <section className="mt-10">
          <h2 id="responses" className="border-border border-b pb-2 text-lg font-semibold">
            {t("responses")}
          </h2>
          <div className="mt-4">
            <ResponseTabs panels={panels} />
          </div>
        </section>
      </article>

      <aside aria-label={t("requestSample")} className="min-w-0 lg:sticky lg:top-8 lg:h-fit">
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
        <div className="border-border bg-card mt-4 rounded-xl border p-4">
          <p className="text-tx-dim text-[11px] font-semibold tracking-wide">{t("canonical")}</p>
          <pre className="text-tx-mute mt-2 overflow-x-auto font-mono text-xs leading-[1.7]">
            <code>{canonicalString(sample)}</code>
          </pre>
          <p className="text-tx-dim mt-3 text-xs leading-relaxed">{t("canonicalHint")}</p>
        </div>
      </aside>
    </div>
  );
}

function ParameterList({ title, items }: { title: string; items: Parameter[] }) {
  return (
    <div className="mt-4">
      <p className="text-tx-dim text-[11px] font-semibold tracking-wide">{title}</p>
      <dl className="divide-border mt-1 divide-y">
        {items.map((item) => (
          <div key={item.name} className="py-3">
            {/* See SchemaTable: the row is the <dt>, not a div around one. */}
            <dt className="flex flex-wrap items-baseline gap-x-2.5">
              <span className="font-mono text-[13px] font-semibold">{item.name}</span>
              <span className="text-tx-dim font-mono text-xs">{typeLabel(item.schema)}</span>
              {item.required === true && (
                <span className="text-danger text-[11px] font-semibold">required</span>
              )}
            </dt>
            {item.description !== undefined && (
              <dd className="text-tx-mute mt-1.5 text-[13px] leading-relaxed">
                {item.description}
              </dd>
            )}
          </div>
        ))}
      </dl>
    </div>
  );
}
