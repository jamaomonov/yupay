import { useQuery } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { Plus } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { T, type AdminPost, type AdminPostList } from "./types";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState, Spinner } from "@/components/States";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

function fmtDate(iso: string): string {
  return new Intl.DateTimeFormat("ru", { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(iso),
  );
}

export function PostsListPage() {
  const navigate = useNavigate();
  const q = useQuery<AdminPostList>({
    queryKey: qk.blogPosts(),
    queryFn: () => apiGet<AdminPostList>("/api/v1/admin/blog/posts"),
  });

  const columns: Column<AdminPost>[] = [
    {
      key: "title",
      header: T.list.columns.title,
      render: (p) => (
        <span>
          <span className="font-medium">{p.translations[0]?.title ?? p.id.slice(0, 8)}</span>
          {p.pin_on_brand ? (
            <span className="ml-2 text-xs uppercase text-[var(--text-secondary)]">
              {T.list.pinned}
            </span>
          ) : null}
        </span>
      ),
    },
    {
      key: "kind",
      header: T.list.columns.kind,
      render: (p) =>
        p.kind === "event" && p.event_ends_at
          ? `${T.kind.event} · ${fmtDate(p.event_ends_at)}`
          : T.kind[p.kind],
      className: "w-32",
    },
    {
      key: "status",
      header: T.list.columns.status,
      render: (p) =>
        p.status === "scheduled" && p.scheduled_for
          ? `${T.status.scheduled} · ${fmtDate(p.scheduled_for)}`
          : T.status[p.status],
      className: "w-36",
    },
    {
      key: "updated",
      header: T.list.columns.updated,
      render: (p) => <span className="text-[var(--text-secondary)]">{fmtDate(p.updated_at)}</span>,
      className: "w-48",
    },
  ];

  return (
    <div>
      <PageHeader
        title={T.list.title}
        description={T.list.description}
        actions={
          <Button onClick={() => void navigate("/blog/new")}>
            <Plus className="size-4" />
            {T.list.create}
          </Button>
        }
      />
      {q.isLoading && <Spinner label="…" />}
      {q.isError && <ErrorState title={T.list.loadError} />}
      {q.data && (
        <DataTable
          rows={q.data.items}
          columns={columns}
          rowKey={(p) => p.id}
          onRowClick={(p) => navigate(`/blog/${p.id}`)}
        />
      )}
      {q.data?.items.length === 0 && (
        <p className="mt-4 text-sm text-[var(--text-secondary)]">
          {T.list.empty}{" "}
          <Link to="/blog/new" className="underline">
            {T.list.create}
          </Link>
        </p>
      )}
    </div>
  );
}
