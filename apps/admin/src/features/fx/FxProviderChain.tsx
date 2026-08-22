import { ChevronDown, ChevronUp } from "lucide-react";

import { formatRate } from "./FxRateCard";
import type { ProviderChainItemOut, ProviderChainOut, ProviderQuoteOut } from "./types";

interface Props {
  data: ProviderChainOut;
  saving: boolean;
  error: string | null;
  onChange: (items: { slug: string; enabled: boolean }[]) => void;
}

export function FxProviderChain({ data, saving, error, onChange }: Props) {
  const items = data.items;

  function move(index: number, delta: number): void {
    const next = index + delta;
    if (next < 0 || next >= items.length) return;
    const reordered = items.slice();
    const a = reordered[index];
    const b = reordered[next];
    if (a === undefined || b === undefined) return;
    reordered[index] = b;
    reordered[next] = a;
    onChange(reordered.map((row) => ({ slug: row.slug, enabled: row.enabled })));
  }

  function toggle(index: number, enabled: boolean): void {
    onChange(
      items.map((row, i) => ({
        slug: row.slug,
        enabled: i === index ? enabled : row.enabled,
      })),
    );
  }

  return (
    <section className="mb-6">
      <h2 className="mb-1 text-sm font-medium">Источники курса FX</h2>
      <p className="mb-3 max-w-2xl text-xs text-[var(--text-secondary)]">
        Система спрашивает провайдеров сверху вниз. Первый живой — основной, остальные подхватывают,
        если он не ответил. CoinGecko считает только USDT. Порядок сохраняется сразу.
      </p>

      <ol className="overflow-hidden rounded-lg border bg-[var(--bg-surface)]">
        {items.map((row, index) => (
          <li
            key={row.slug}
            className="flex flex-col gap-3 border-b p-3 last:border-b-0 sm:flex-row sm:items-center sm:gap-4"
          >
            <div className="flex items-center gap-2">
              <span className="w-5 text-center font-mono text-xs text-[var(--text-secondary)]">
                {index + 1}
              </span>
              <div className="flex flex-col">
                <button
                  type="button"
                  aria-label={`Выше: ${row.title}`}
                  disabled={saving || index === 0}
                  onClick={() => {
                    move(index, -1);
                  }}
                  className="rounded p-0.5 text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:opacity-30"
                >
                  <ChevronUp className="size-4" />
                </button>
                <button
                  type="button"
                  aria-label={`Ниже: ${row.title}`}
                  disabled={saving || index === items.length - 1}
                  onClick={() => {
                    move(index, 1);
                  }}
                  className="rounded p-0.5 text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:opacity-30"
                >
                  <ChevronDown className="size-4" />
                </button>
              </div>
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{row.title}</span>
                <RoleBadge role={row.role} />
              </div>
              <p className="text-[11px] text-[var(--text-secondary)]">
                {row.kind === "crypto" ? "крипта" : "фиат"} · {row.slug}
              </p>
            </div>

            <dl className="grid flex-1 grid-cols-3 gap-2 text-sm">
              {data.quotes.map((quote) => {
                const cell = row.quotes.find((q) => q.quote === quote);
                return (
                  <div key={quote}>
                    <dt className="text-[10px] uppercase tracking-wide text-[var(--text-secondary)]">
                      {quote}
                    </dt>
                    <dd className="font-mono text-xs">{formatQuote(cell)}</dd>
                  </div>
                );
              })}
            </dl>

            <label className="flex shrink-0 items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={row.enabled}
                disabled={saving}
                onChange={(e) => {
                  toggle(index, e.target.checked);
                }}
              />
              В цепочке
            </label>
          </li>
        ))}
      </ol>
      {error ? <p className="mt-2 text-sm text-[var(--danger)]">{error}</p> : null}
    </section>
  );
}

function RoleBadge({ role }: { role: string }) {
  const label =
    role === "primary"
      ? "Основной"
      : role === "fallback"
        ? "Запасной"
        : role === "unconfigured"
          ? "Нет ключа"
          : "Выключен";
  const tone =
    role === "primary" ? "bg-[var(--bg-muted)] font-medium" : "text-[var(--text-secondary)]";
  return <span className={`rounded px-1.5 py-0.5 text-[11px] ${tone}`}>{label}</span>;
}

function formatQuote(cell: ProviderQuoteOut | undefined): string {
  if (cell?.rate) return formatRate(cell.rate);
  if (cell?.error === "не обслуживает эту пару") return "—";
  if (cell?.error) return "ошибка";
  return "—";
}
