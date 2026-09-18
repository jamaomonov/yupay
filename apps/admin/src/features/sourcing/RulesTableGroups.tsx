/** Brand-grouped rendering for `RulesTable`'s rule list — split out to keep
 *  `RulesTable.tsx` under the 300-LOC soft limit (AGENTS.md §6). Purely
 *  presentational: takes the already-filtered, already-grouped rows and the
 *  shared column definitions and renders one section per brand, each with
 *  its own rule count, reusing the same `DataTable` every ungrouped render
 *  used before this — filtering stays entirely upstream in `RulesTable`. */

import { Badge } from "@/components/Badge";
import { DataTable, type Column } from "@/components/DataTable";

export interface RuleGroup<T> {
  /** Stable React key — the brand id (or a sentinel for "no brand"), never
   *  the display `label`: two brands can share a Russian name, and two
   *  identically-labelled sections would otherwise collide on the same
   *  React key (whole-branch review #3). */
  key: string;
  label: string;
  rows: T[];
}

export function RulesTableGroups<T>({
  groups,
  columns,
  rowKey,
}: {
  groups: RuleGroup<T>[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
}) {
  return (
    <div className="space-y-4">
      {groups.map((group) => (
        <section
          key={group.key}
          aria-label={`${group.label} (${group.rows.length.toString()})`}
          className="space-y-2"
        >
          <div className="flex items-center gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
              {group.label}
            </h3>
            <Badge tone="bg-[var(--bg-muted)] text-[var(--text-secondary)]">
              {group.rows.length}
            </Badge>
          </div>
          <DataTable rows={group.rows} columns={columns} rowKey={rowKey} />
        </section>
      ))}
    </div>
  );
}
