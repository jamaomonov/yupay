import { notFound } from "next/navigation";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { CodeTabs } from "@/components/docs/CodeTabs";
import { Prose } from "@/components/docs/Prose";
import { SchemaTable } from "@/components/docs/SchemaTable";
import { routing } from "@/i18n/routing";
import { contract, endpoints } from "@/lib/contract";
import { exampleJson } from "@/lib/example";

export const dynamicParams = false;

export function generateStaticParams() {
  return routing.locales.flatMap((locale) =>
    Object.keys(contract().components.schemas).map((name) => ({ locale, name })),
  );
}

export default async function SchemaPage({
  params,
}: {
  params: Promise<{ locale: string; name: string }>;
}) {
  const { locale, name } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("merchant.docs");

  const node = contract().components.schemas[name];
  if (node === undefined) notFound();

  // Which endpoints hand this model over — the question a reader arriving
  // from a `$ref` link actually has, and one the schema alone cannot answer.
  const used = endpoints().filter((endpoint) =>
    JSON.stringify(endpoint.operation).includes(`"#/components/schemas/${name}"`),
  );

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-8">
      <p className="text-tx-dim text-[11px] font-semibold tracking-[0.09em]">{t("groupSchemas")}</p>
      <h1 className="font-display mt-1.5 text-2xl font-semibold tracking-tight">{name}</h1>
      {node.description !== undefined && (
        <Prose text={node.description} className="text-tx-mute mt-4 max-w-2xl" />
      )}

      <section className="mt-9">
        <h2 className="border-border border-b pb-2 text-lg font-semibold">{t("fields")}</h2>
        <div className="mt-4">
          <SchemaTable node={node} locale={locale} />
        </div>
      </section>

      <section className="mt-9">
        <h2 className="border-border border-b pb-2 text-lg font-semibold">{t("example")}</h2>
        <div className="mt-4">
          <CodeTabs
            copyLabel={t("copy")}
            copiedLabel={t("copied")}
            tabs={[{ id: "json", label: "JSON", code: exampleJson(node) }]}
          />
        </div>
      </section>

      {used.length > 0 && (
        <section className="mt-9">
          <h2 className="border-border border-b pb-2 text-lg font-semibold">{t("usedBy")}</h2>
          <ul className="mt-4 space-y-2">
            {used.map((endpoint) => (
              <li key={endpoint.id} className="flex flex-wrap items-baseline gap-2.5 text-sm">
                <span className="text-tx-dim font-mono text-[11px] font-bold">
                  {endpoint.method}
                </span>
                <a
                  href={`/${locale}/docs/api/${endpoint.id}`}
                  className="underline-offset-4 hover:underline"
                >
                  {endpoint.operation.summary ?? endpoint.path}
                </a>
                <code className="text-tx-dim font-mono text-[12px]">{endpoint.path}</code>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
