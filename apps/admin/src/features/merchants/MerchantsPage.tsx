/**
 * Merchant list + creation (`/merchants`) — Merchant B2B M1, Task 7.
 *
 * List every reseller with its USD deposit balance (one grouped backend
 * query), and create new ones from a dialog. Row click opens the detail
 * screen (`MerchantDetail`), where freeze and deposit credits live.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { Plus } from "lucide-react";
import { useId, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  T,
  createMerchant,
  fetchMerchants,
  fill,
  formatUsd,
  type MerchantListOut,
  type MerchantOut,
} from "./api";

import type { ApiError } from "@/lib/api";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { StatusChip } from "@/components/StatusChip";
import { useToast } from "@/components/Toast";
import { extractApiMessage } from "@/lib/apiError";
import { qk } from "@/lib/queryKeys";
import { useDialog } from "@/lib/useDialog";

export function MerchantsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const [createOpen, setCreateOpen] = useState(false);
  // One idempotency key per logical create attempt: minted when the dialog
  // opens, stable across retries of that attempt (an error keeps the dialog
  // up), replaced on the next open.
  const createKeyRef = useRef("");

  const listQuery = useQuery<MerchantListOut>({
    queryKey: qk.merchants(),
    queryFn: fetchMerchants,
  });

  const createMutation = useMutation<MerchantOut, ApiError, string>({
    mutationFn: (title) => createMerchant(title, createKeyRef.current),
    onSuccess: (merchant) => {
      setCreateOpen(false);
      toast.success(T.list.createDialog.created);
      // Seed the cache with the fresh row BEFORE navigating: the detail
      // screen reads this cache, and racing the invalidated refetch used to
      // flash «Мерчант не найден» until the list came back.
      qc.setQueryData<MerchantListOut>(qk.merchants(), (prev) =>
        prev ? { ...prev, items: [merchant, ...prev.items] } : { items: [merchant] },
      );
      void qc.invalidateQueries({ queryKey: qk.merchants() });
      // Straight to the detail screen — the next step is almost always the
      // first deposit credit.
      void navigate(`/merchants/${merchant.id}`);
    },
    onError: (err) => {
      toast.error(fill(T.list.createDialog.error, { message: extractApiMessage(err) }));
    },
  });

  const columns: Column<MerchantOut>[] = [
    {
      key: "title",
      header: T.list.columns.title,
      render: (m) => <span className="font-medium">{m.title}</span>,
      sortAccessor: (m) => m.title,
    },
    {
      key: "status",
      header: T.list.columns.status,
      render: (m) => <StatusChip domain="merchantStatus" value={m.status} />,
      className: "w-32",
      sortAccessor: (m) => m.status,
    },
    {
      key: "balance",
      header: T.list.columns.balance,
      render: (m) => <span className="font-medium">{formatUsd(m.deposit_balance)}</span>,
      className: "w-36 text-right",
      // Sorting (not display) may go through Number — the shown string stays Decimal.
      sortAccessor: (m) => Number(m.deposit_balance),
    },
    {
      key: "created",
      header: T.list.columns.created,
      render: (m) => (
        <span className="text-[var(--text-secondary)]">
          {new Date(m.created_at).toLocaleDateString("ru")}
        </span>
      ),
      className: "w-28",
      sortAccessor: (m) => new Date(m.created_at),
    },
  ];

  return (
    <div>
      <PageHeader
        title={T.list.title}
        description={T.list.description}
        actions={
          <Button
            onClick={() => {
              createKeyRef.current = `merchant-create-${crypto.randomUUID()}`;
              setCreateOpen(true);
            }}
          >
            <Plus className="size-4" />
            {T.list.create}
          </Button>
        }
      />

      {listQuery.isError && <p className="mb-4 text-sm text-[var(--danger)]">{T.list.loadError}</p>}

      <DataTable
        rows={listQuery.data?.items ?? []}
        columns={columns}
        rowKey={(m) => m.id}
        loading={listQuery.isLoading}
        empty={T.list.empty}
        ariaLabel={T.list.title}
        onRowClick={(m) => {
          void navigate(`/merchants/${m.id}`);
        }}
      />

      {createOpen && (
        <CreateMerchantDialog
          busy={createMutation.isPending}
          onCancel={() => {
            setCreateOpen(false);
          }}
          onSubmit={(title) => {
            createMutation.mutate(title);
          }}
        />
      )}
    </div>
  );
}

interface CreateDialogProps {
  busy: boolean;
  onCancel: () => void;
  onSubmit: (title: string) => void;
}

function CreateMerchantDialog({ busy, onCancel, onSubmit }: CreateDialogProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const titleId = useId();
  const inputId = useId();
  const [title, setTitle] = useState("");

  useDialog({
    open: true,
    onClose: onCancel,
    containerRef: dialogRef,
    initialFocus: () => inputRef.current?.focus(),
  });

  return (
    <div
      ref={dialogRef}
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 px-4 pt-[12vh] backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <form
        className="w-full max-w-md rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-4 text-[var(--text-primary)] shadow-[var(--shadow-md)]"
        onSubmit={(e) => {
          e.preventDefault();
          const cleaned = title.trim();
          if (cleaned && !busy) onSubmit(cleaned);
        }}
      >
        <h2 id={titleId} className="mb-3 text-sm font-semibold">
          {T.list.createDialog.title}
        </h2>
        <label
          htmlFor={inputId}
          className="text-xs font-medium uppercase text-[var(--text-secondary)]"
        >
          {T.list.createDialog.titleLabel}
        </label>
        <Input
          ref={inputRef}
          id={inputId}
          value={title}
          onChange={(e) => {
            setTitle(e.target.value);
          }}
          placeholder={T.list.createDialog.titlePlaceholder}
          className="mt-1"
        />
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" type="button" onClick={onCancel} disabled={busy}>
            {T.list.createDialog.cancel}
          </Button>
          <Button type="submit" disabled={busy || !title.trim()}>
            {busy ? "…" : T.list.createDialog.submit}
          </Button>
        </div>
      </form>
    </div>
  );
}
