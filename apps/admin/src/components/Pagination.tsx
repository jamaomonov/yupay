import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@yupay/ui";

interface Props {
  total: number;
  limit: number;
  offset: number;
  onPageChange: (nextOffset: number) => void;
  /** Optional override of the page-size — currently fixed but exposed for
   *  future use. */
  pageSizeLabel?: string;
}

export function Pagination({
  total,
  limit,
  offset,
  onPageChange,
  pageSizeLabel,
}: Props) {
  if (total <= limit) return null;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  const canPrev = offset > 0;
  const canNext = to < total;
  return (
    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-[--color-muted]">
      <span>
        {from}–{to} из {total}
        {pageSizeLabel ? ` · ${pageSizeLabel}` : ""}
      </span>
      <div className="flex gap-2">
        <Button
          variant="ghost"
          size="sm"
          disabled={!canPrev}
          onClick={() => onPageChange(Math.max(0, offset - limit))}
        >
          <ChevronLeft className="size-4" />
          Назад
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={!canNext}
          onClick={() => onPageChange(offset + limit)}
        >
          Вперёд
          <ChevronRight className="size-4" />
        </Button>
      </div>
    </div>
  );
}
