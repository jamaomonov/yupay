import { Button } from "@yupay/ui";
import { ChevronLeft, ChevronRight } from "lucide-react";

interface Props {
  total: number;
  limit: number;
  offset: number;
  onPageChange: (nextOffset: number) => void;
  /** Optional override of the page-size — currently fixed but exposed for
   *  future use. */
  pageSizeLabel?: string;
}

export function Pagination({ total, limit, offset, onPageChange, pageSizeLabel }: Props) {
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  const canPrev = offset > 0;
  const canNext = to < total;
  // The count stays visible even when everything fits on one page: after
  // filtering, "12 из 12" is the only confirmation the operator has that the
  // filter did what they meant. Hiding it (the previous `total <= limit` early
  // return) removed the feedback exactly when the result set was small.
  const showControls = canPrev || canNext;
  return (
    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-[var(--text-secondary)]">
      <span>
        {from}–{to} из {total}
        {pageSizeLabel ? ` · ${pageSizeLabel}` : ""}
      </span>
      <div className={showControls ? "flex gap-2" : "hidden"}>
        <Button
          variant="secondary"
          size="sm"
          disabled={!canPrev}
          onClick={() => {
            onPageChange(Math.max(0, offset - limit));
          }}
          aria-label="Предыдущая страница"
        >
          <ChevronLeft className="size-4" aria-hidden />
          Назад
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={!canNext}
          onClick={() => {
            onPageChange(offset + limit);
          }}
          aria-label="Следующая страница"
        >
          Вперёд
          <ChevronRight className="size-4" aria-hidden />
        </Button>
      </div>
    </div>
  );
}
