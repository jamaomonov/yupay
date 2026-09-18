/** Denomination picker for the mapping wizard's step 4 — **NOVA and
 *  G-Engine only**. G2B keeps its own live picker (`DenomPicker` in
 *  `gameWidgets.tsx`, reading `GET /g2b/games/{code}/catalogue` directly);
 *  the backend never moved G2B's denominations into `supplier_catalog_cache`
 *  and its `sync-denominations` route only accepts `nova`/`gengine`
 *  (`DENOM_SYNCABLE_SUPPLIERS` — see `catalog_sync.py`), so a G2B game routed
 *  through this component would show a permanently empty cache with a pull
 *  button that 404s. `MappingEditPage` branches on `supplier` to pick between
 *  the two.
 *
 * Same cache as `CatalogPicker` (`supplier_catalog_cache` through
 * `GET /admin/integrations/catalog`), narrowed with `kind=game_denom` and
 * `parent_external_id=<the chosen game>`. Row rendering is `CatalogRow`,
 * imported rather than re-implemented — see `pickers.tsx`.
 *
 * This is not just `CatalogPicker` with a different `kind`: denominations are
 * only ever cached for a game some mapping already points at (see the
 * backend's `integrations/README.md`), so a game an operator is *just now*
 * mapping for the first time has an empty cache by construction, not by
 * accident. An empty dropdown with no explanation would leave the operator
 * stuck. Instead this shows what happened and offers `POST
 * /admin/integrations/{supplier}/games/{game_id}/sync-denominations` — a
 * one-shot pull for this one game — right where the gap was noticed, then
 * falls through to the normal picker once the pull lands something.
 *
 * Operates on the plain `external_variant_id` string the wizard already
 * carries (`value`/`onChange: (next: string) => void`), matching the shape
 * of `DenomPicker`'s own signature, so `MappingEditPage` can swap between the
 * two without a second piece of state to hold the picker's selection. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { useState } from "react";

import { CatalogRow } from "./pickers";
import {
  syntheticCatalogEntry,
  type CatalogEntry,
  type CatalogListOut,
  type SyncDenominationsResult,
} from "./types";

import { Combobox } from "@/components/Combobox";
import { apiGet, apiPost, formatApiError, type ApiError } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { useDebouncedValue } from "@/lib/useDebouncedValue";

interface DenomCatalogPickerProps {
  supplier: string;
  /** The game's `external_id`, chosen in step 3 — null until then. */
  gameExternalId: string | null;
  value: string;
  onChange: (nextExternalId: string) => void;
  disabled?: boolean;
  id?: string;
}

export function DenomCatalogPicker({
  supplier,
  gameExternalId,
  value,
  onChange,
  disabled,
  id,
}: DenomCatalogPickerProps) {
  const [query, setQuery] = useState("");
  const debounced = useDebouncedValue(query, 200);
  const qc = useQueryClient();

  const catalogFilters = {
    supplierSlug: supplier,
    kind: "game_denom",
    search: debounced,
    parentExternalId: gameExternalId,
  };

  const { data, isLoading, isError } = useQuery<CatalogListOut>({
    queryKey: qk.integrationCatalog(catalogFilters),
    queryFn: () => {
      const params = new URLSearchParams({
        supplier_slug: supplier,
        kind: "game_denom",
        parent_external_id: gameExternalId ?? "",
        limit: "50",
      });
      if (debounced) params.set("search", debounced);
      return apiGet<CatalogListOut>(`/api/v1/admin/integrations/catalog?${params.toString()}`);
    },
    enabled: Boolean(gameExternalId),
    staleTime: 60_000,
  });

  const sync = useMutation<SyncDenominationsResult, ApiError>({
    mutationFn: () =>
      // One fresh Idempotency-Key per attempt, minted here rather than
      // hoisted — see bulkSwitch.ts for why reusing one across a retry is
      // wrong: it would replay a stale (possibly empty) result instead of
      // trying again.
      apiPost<SyncDenominationsResult>(
        `/api/v1/admin/integrations/${supplier}/games/${encodeURIComponent(gameExternalId ?? "")}/sync-denominations`,
        {},
        { "Idempotency-Key": crypto.randomUUID() },
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.integrationCatalog(catalogFilters) });
    },
  });

  if (!gameExternalId) {
    return (
      <p className="text-xs text-[var(--text-tertiary)]">
        Выберите игру выше, чтобы загрузить список номиналов.
      </p>
    );
  }

  const items = data?.items ?? [];
  // A blank base list (no search typed) is the "cache never pulled" case
  // this widget exists for — a search that simply matched nothing falls
  // through to the ordinary combobox with "Ничего не найдено" instead,
  // since re-pulling the whole game won't fix a typo.
  const cacheEmpty = !isLoading && !isError && items.length === 0 && debounced === "";

  const selected: CatalogEntry | null = value.trim()
    ? (items.find((e) => e.external_id === value) ??
      syntheticCatalogEntry(supplier, "game_denom", value, gameExternalId))
    : null;

  if (cacheEmpty) {
    return (
      <div className="space-y-2 rounded-md border border-dashed border-[var(--border-default)] bg-[var(--bg-muted)] p-3">
        <p className="text-xs text-[var(--text-secondary)]">
          В кэше нет номиналов для этой игры — возможно, поставщик только что добавил позицию, а
          каталог ещё не подтягивался.
        </p>
        <Button
          type="button"
          size="sm"
          onClick={() => {
            sync.mutate();
          }}
          disabled={sync.isPending || disabled}
        >
          {sync.isPending ? "Подтягиваем номиналы…" : "Подтянуть номиналы у поставщика"}
        </Button>
        {sync.isError && (
          <p role="alert" className="text-xs text-[var(--danger)]">
            Не удалось подтянуть номиналы: {formatApiError(sync.error)}
          </p>
        )}
        {sync.isSuccess && sync.data.denominations_synced === 0 && (
          <p className="text-xs text-[var(--text-tertiary)]">
            Поставщик не вернул ни одного номинала для этой игры.
          </p>
        )}
      </div>
    );
  }

  return (
    <Combobox
      id={id}
      ariaLabel="Номинал"
      value={selected}
      onChange={(next) => {
        onChange(next?.external_id ?? "");
      }}
      items={items}
      query={query}
      onQueryChange={setQuery}
      loading={isLoading}
      errorMessage={isError ? "Не удалось загрузить номиналы" : null}
      emptyMessage="Ничего не найдено"
      disabled={disabled}
      placeholder="Выберите номинал…"
      keyFor={(e) => `${e.kind}-${e.external_id}`}
      renderSelected={(e) => <CatalogRow entry={e} kind="game_denom" compact />}
      renderItem={(e) => <CatalogRow entry={e} kind="game_denom" />}
    />
  );
}
