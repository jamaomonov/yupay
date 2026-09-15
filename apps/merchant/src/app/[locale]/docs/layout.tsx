import { getTranslations, setRequestLocale } from "next-intl/server";

import type { NavGroup } from "@/components/docs/DocsShell";

import { DocsShell } from "@/components/docs/DocsShell";
import { pathFor } from "@/lib/locale-href";
import { contract, endpoints } from "@/lib/contract";

/**
 * The documentation shell, with its navigation built from the contract.
 *
 * A Server Component, so the schema is read at build time and the whole
 * sidebar is in the HTML — a reference whose list of endpoints arrived after
 * a fetch would be invisible to a search engine and blank for a second to
 * everybody else.
 */
export default async function DocsLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("merchant.docs");

  const guides: NavGroup = {
    title: t("groupStart"),
    items: [
      { href: pathFor(locale, "/docs"), label: t("navIntroduction") },
      { href: pathFor(locale, "/docs/authentication"), label: t("navAuthentication") },
      { href: pathFor(locale, "/docs/quickstart"), label: t("navQuickstart") },
      { href: pathFor(locale, "/docs/errors"), label: t("navErrors") },
      { href: pathFor(locale, "/docs/webhooks"), label: t("navWebhooks") },
    ],
  };

  // One group per tag, in the order the contract lists them, so the reference
  // reads in the order somebody integrates rather than alphabetically.
  const byTag = new Map<string, NavGroup>();
  for (const tag of contract().tags ?? []) {
    byTag.set(tag.name, { title: tag.name, items: [] });
  }
  for (const endpoint of endpoints()) {
    const group = byTag.get(endpoint.tag) ?? { title: endpoint.tag, items: [] };
    group.items.push({
      href: pathFor(locale, `/docs/api/${endpoint.id}`),
      label: endpoint.operation.summary ?? endpoint.path,
      method: endpoint.method,
    });
    byTag.set(endpoint.tag, group);
  }

  const schemas: NavGroup = {
    title: t("groupSchemas"),
    items: Object.keys(contract().components.schemas)
      .sort((a, b) => a.localeCompare(b))
      .map((name) => ({ href: pathFor(locale, `/docs/schemas/${name}`), label: name })),
  };

  const groups = [guides, ...[...byTag.values()].filter((g) => g.items.length > 0), schemas];

  return (
    <DocsShell groups={groups} brand={pathFor(locale, "")}>
      {children}
    </DocsShell>
  );
}
