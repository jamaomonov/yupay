/** Browse the cached G2B game catalog and jump into the import wizard. */
import { useQuery } from "@tanstack/react-query";
import { Database, Search } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  capabilitiesFor,
  SUPPLIER_LABELS,
  type CatalogEntry,
  type MappedProductIdsOut,
} from "./types";

import { DataTable } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState } from "@/components/States";
import { apiGet } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";
import { qk } from "@/lib/queryKeys";
import { useDebouncedValue } from "@/lib/useDebouncedValue";

interface CatalogListOut {
  items: CatalogEntry[];
}

export function SupplierCatalogPage() {
  const { slug = "g2b" } = useParams<{ slug?: string }>();
  const label = (SUPPLIER_LABELS as Record<string, string>)[slug] ?? slug;
  // Only G2B has an importer (`GameImportPage` posts to the G2B-specific
  // `POST /g2b/import` regardless of which supplier's catalogue linked to
  // it) — see `capabilitiesFor`'s docstring.
  const canImport = capabilitiesFor(slug).gameImport;
  const [search, setSearch] = useState("");
  const q = useDebouncedValue(search, 300);

  const games = useQuery<CatalogListOut>({
    queryKey: qk.integrationCatalog({ supplierSlug: slug, kind: "game", search: q }),
    queryFn: () =>
      apiGet<CatalogListOut>(
        `/api/v1/admin/integrations/catalog?supplier_slug=${slug}&kind=game` +
          (q ? `&search=${encodeURIComponent(q)}` : ""),
      ),
  });

  // The whole "already imported" set in one call. This used to read the
  // mapping list, which answers its first 200 rows — ~8600 exist after the
  // 2026-10 bulk import, so every game past the first page showed as not yet
  // imported. The products endpoint is the distinct ids, nothing else.
  // Key built inline (`qk` has no entry for this endpoint yet), under the
  // `["admin","integrations","mappings"]` prefix so a future bare-prefix
  // invalidation would reach it. Today nothing writes mappings from this
  // page, and the import wizard navigates away, so it refreshes on its own
  // staleness like before.
  const mappedProducts = useQuery<MappedProductIdsOut>({
    queryKey: ["admin", "integrations", "mappings", "products", slug] as const,
    queryFn: () =>
      apiGet<MappedProductIdsOut>(
        `/api/v1/admin/integrations/mappings/products?supplier_slug=${slug}&kind=game`,
      ),
  });

  const imported = new Set(mappedProducts.data?.items ?? []);

  return (
    <div>
      <PageHeader
        title={`Каталог · ${label}`}
        description="Игры поставщика из локального кэша. Откройте игру, чтобы импортировать её как бренд с номиналами."
        breadcrumbs={[
          { label: "Интеграции", to: "/integrations" },
          { label, to: `/integrations/${slug}` },
          { label: "Каталог" },
        ]}
      />

      <label className="mb-4 flex max-w-sm items-center gap-2 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3">
        <Search className="size-4 text-[var(--text-tertiary)]" />
        <input
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
          }}
          placeholder="Поиск игры…"
          className="h-9 flex-1 bg-transparent text-sm outline-none"
        />
      </label>

      {games.isError ? (
        <ErrorState
          description={extractApiMessage(games.error)}
          onRetry={() => void games.refetch()}
          retryPending={games.isFetching}
        />
      ) : (
        <DataTable
          rows={games.data?.items ?? []}
          rowKey={(r) => r.external_id}
          loading={games.isLoading}
          busy={games.isFetching}
          ariaLabel="Каталог игр поставщика"
          empty="Каталог пуст. Сначала синхронизируйте каталог на странице поставщика."
          columns={[
            {
              key: "title",
              header: "Игра",
              render: (r) => <span className="font-medium">{r.title}</span>,
            },
            {
              key: "code",
              header: "game_code",
              render: (r) => <code className="font-mono text-xs">{r.external_id}</code>,
            },
            {
              key: "status",
              header: "",
              render: (r) =>
                imported.has(r.external_id) ? (
                  <span className="rounded bg-[var(--bg-accent-soft)] px-2 py-0.5 text-xs text-[var(--accent)]">
                    импортирована
                  </span>
                ) : null,
            },
            {
              key: "action",
              header: "",
              render: (r) =>
                canImport ? (
                  <Link
                    to={`/integrations/${slug}/catalog/${encodeURIComponent(r.external_id)}`}
                    className="inline-flex items-center gap-1 text-sm font-medium text-[var(--accent)] hover:underline"
                  >
                    <Database className="size-4" /> Импортировать →
                  </Link>
                ) : null,
            },
          ]}
        />
      )}
    </div>
  );
}
