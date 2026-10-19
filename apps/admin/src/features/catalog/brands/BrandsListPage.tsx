import { useQuery } from "@tanstack/react-query";
import { Button, Select } from "@yupay/ui";
import { Plus } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { type FlagFilter, filterBrands, parseFlagFilter } from "./brand-filters";

import type { Brand } from "../types";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { SearchBox } from "@/components/SearchBox";
import { Spinner } from "@/components/States";
import { Thumb } from "@/components/Thumb";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { type SearchParamCodec, useSearchParamsState } from "@/lib/useSearchParamsState";

const flagCodec: SearchParamCodec<FlagFilter> = {
  parse: parseFlagFilter,
  serialize: (v) => v,
  isDefault: (v) => v === "",
};

interface FlagSelectProps {
  label: string;
  value: FlagFilter;
  onChange: (next: FlagFilter) => void;
  yes: string;
  no: string;
}

/** «Все / да / нет» for one brand flag. */
function FlagSelect({ label, value, onChange, yes, no }: FlagSelectProps) {
  return (
    <Select
      aria-label={label}
      value={value}
      onChange={(e) => {
        onChange(parseFlagFilter(e.target.value));
      }}
      containerClassName="w-auto"
    >
      <option value="">{label}: все</option>
      <option value="yes">{yes}</option>
      <option value="no">{no}</option>
    </Select>
  );
}

const mark = (on: boolean) => (on ? "✓" : "—");

export function BrandsListPage() {
  const navigate = useNavigate();
  const q = useQuery<Brand[]>({
    queryKey: qk.brands(),
    queryFn: () => apiGet<Brand[]>("/api/v1/admin/catalog/brands"),
  });
  const [active, setActive] = useSearchParamsState<FlagFilter>("active", "", flagCodec);
  const [retail, setRetail] = useSearchParamsState<FlagFilter>("retail", "", flagCodec);
  const [b2b, setB2b] = useSearchParamsState<FlagFilter>("b2b", "", flagCodec);
  const [query, setQuery] = useSearchParamsState("q", "");
  const filtered = q.data ? filterBrands(q.data, { active, retail, b2b, query }) : undefined;
  const filtering = active !== "" || retail !== "" || b2b !== "" || query.trim() !== "";

  const columns: Column<Brand>[] = [
    {
      key: "name",
      header: "Бренд",
      render: (b) => (
        <div className="flex items-center gap-2">
          <Thumb
            src={b.logo_url}
            name={b.translations.find((t) => t.locale === "ru")?.name ?? b.slug}
          />
          {b.accent_color && (
            <span
              className="inline-block size-3 rounded-full"
              style={{ background: b.accent_color }}
            />
          )}
          <span>{b.translations.find((t) => t.locale === "ru")?.name ?? b.slug}</span>
        </div>
      ),
    },
    { key: "slug", header: "Slug", render: (b) => <code className="text-xs">{b.slug}</code> },
    { key: "sort", header: "Порядок", render: (b) => b.sort_order, className: "w-24" },
    {
      key: "active",
      header: "Статус",
      render: (b) => mark(b.active),
      className: "w-16",
    },
    { key: "retail", header: "Витрина", render: (b) => mark(b.visible_retail), className: "w-20" },
    { key: "b2b", header: "Мерчанты", render: (b) => mark(b.visible_b2b), className: "w-24" },
  ];

  return (
    <div>
      <PageHeader
        title="Бренды"
        description="Игры, сервисы, подписки. Один бренд → много продуктов."
        actions={
          <Button onClick={() => navigate("/brands/new")}>
            <Plus className="size-4" />
            Добавить бренд
          </Button>
        }
      />
      <section className="mb-4 flex flex-wrap items-center gap-3">
        <SearchBox value={query} onChange={setQuery} placeholder="Поиск по названию или slug…" />
        <FlagSelect
          label="Статус"
          value={active}
          onChange={setActive}
          yes="Активные"
          no="Неактивные"
        />
        <FlagSelect
          label="Витрина"
          value={retail}
          onChange={setRetail}
          yes="Видны клиентам"
          no="Скрыты от клиентов"
        />
        <FlagSelect
          label="Мерчанты"
          value={b2b}
          onChange={setB2b}
          yes="Доступны мерчантам"
          no="Недоступны мерчантам"
        />
        {filtering && filtered && q.data && (
          <span className="text-sm text-[var(--text-secondary)]">
            {filtered.length} из {q.data.length}
          </span>
        )}
        {filtering && (
          <Button
            variant="ghost"
            onClick={() => {
              setActive("");
              setRetail("");
              setB2b("");
              setQuery("");
            }}
          >
            Сбросить
          </Button>
        )}
      </section>
      {q.isLoading && <Spinner label="Загрузка…" />}
      {q.isError && <p className="text-sm text-[var(--danger)]">Ошибка загрузки.</p>}
      {filtered && (
        <DataTable
          rows={filtered}
          columns={columns}
          rowKey={(b) => b.id}
          onRowClick={(b) => navigate(`/brands/${b.id}`)}
        />
      )}
      {filtering && filtered?.length === 0 && q.data?.length !== 0 && (
        <p className="mt-4 text-sm text-[var(--text-secondary)]">Под фильтры ничего не подходит.</p>
      )}
      {q.data?.length === 0 && (
        <p className="mt-4 text-sm text-[var(--text-secondary)]">
          Ничего нет.{" "}
          <Link to="/brands/new" className="underline">
            Создать первый
          </Link>
          ?
        </p>
      )}
    </div>
  );
}
