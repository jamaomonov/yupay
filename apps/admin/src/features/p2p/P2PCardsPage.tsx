/** `/payments/p2p-cards` — switches panel plus the cards table with add and edit. */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { Plus } from "lucide-react";
import { useState } from "react";

import {
  fetchCards,
  fetchSettings,
  formatUzs,
  relativeTime,
  T,
  p2pErrorMessage,
  type P2PCard,
} from "./api";
import { P2PCardForm } from "./P2PCardForm";
import { P2PSettingsPanel } from "./P2PSettingsPanel";

import { Badge } from "@/components/Badge";
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState, Spinner } from "@/components/States";
import { qk } from "@/lib/queryKeys";

type Editing = { kind: "none" } | { kind: "new" } | { kind: "edit"; card: P2PCard };

export function P2PCardsPage() {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<Editing>({ kind: "none" });
  const settings = useQuery({ queryKey: qk.p2pSettings(), queryFn: fetchSettings });
  const cards = useQuery({ queryKey: qk.p2pCards(), queryFn: fetchCards });
  const C = T.cards;

  const columns: Column<P2PCard>[] = [
    { key: "label", header: C.table.label, render: (c) => c.label },
    { key: "last4", header: C.table.last4, render: (c) => `*${c.pan_last4}` },
    { key: "holder", header: C.table.holder, render: (c) => c.holder_name },
    { key: "network", header: C.table.network, render: (c) => c.network.toUpperCase() },
    { key: "active", header: C.table.active, render: (c) => (c.active ? C.yes : C.no) },
    { key: "min", header: C.table.min, render: (c) => formatUzs(c.min_amount_uzs) },
    { key: "max", header: C.table.max, render: (c) => formatUzs(c.max_amount_uzs) },
    {
      key: "daily",
      header: C.table.daily,
      render: (c) => (c.daily_limit_uzs === null ? C.noLimit : formatUzs(c.daily_limit_uzs)),
    },
    { key: "today", header: C.table.today, render: (c) => formatUzs(c.matched_today_uzs) },
    {
      key: "health",
      header: C.table.health,
      render: (c) => (
        <span className="flex flex-wrap items-center gap-1.5">
          <span>{c.last_incoming_at ? relativeTime(c.last_incoming_at) : C.health.never}</span>
          {c.chain_ok_last === false ? (
            <Badge tone="bg-[var(--danger-soft)] text-[var(--danger-fg)]">
              {C.health.chainBroken}
            </Badge>
          ) : null}
        </span>
      ),
    },
    {
      key: "edit",
      header: "",
      render: (c) => (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setEditing({ kind: "edit", card: c });
          }}
        >
          {C.table.edit}
        </Button>
      ),
    },
  ];

  const done = () => {
    setEditing({ kind: "none" });
    void qc.invalidateQueries({ queryKey: qk.p2pCards() });
  };

  return (
    <div>
      <PageHeader
        title={C.title}
        description={C.description}
        actions={
          <Button
            onClick={() => {
              setEditing({ kind: "new" });
            }}
          >
            <Plus className="size-4" aria-hidden /> {C.form.add}
          </Button>
        }
      />

      {settings.data ? <P2PSettingsPanel settings={settings.data} /> : null}
      {settings.isError ? (
        <ErrorState
          description={p2pErrorMessage(settings.error)}
          onRetry={() => void settings.refetch()}
        />
      ) : null}

      {editing.kind !== "none" ? (
        <P2PCardForm
          key={editing.kind === "edit" ? editing.card.id : "new"}
          card={editing.kind === "edit" ? editing.card : null}
          onDone={done}
          onCancel={() => {
            setEditing({ kind: "none" });
          }}
        />
      ) : null}

      {cards.isLoading ? <Spinner label="Загрузка…" /> : null}
      {cards.isError ? (
        <ErrorState
          description={p2pErrorMessage(cards.error)}
          onRetry={() => void cards.refetch()}
        />
      ) : null}
      {cards.data ? (
        <DataTable
          rows={cards.data}
          columns={columns}
          rowKey={(c) => c.id}
          empty={C.empty}
          ariaLabel={C.title}
        />
      ) : null}
    </div>
  );
}
