/**
 * A person, as a link: their avatar and their name.
 *
 * Replaces a clickable UUID. An id tells an operator nothing they can
 * recognise, and every screen that showed one made them open it to find out
 * who they were looking at.
 *
 * Degrades rather than disappears: no avatar falls back to the initial (see
 * `Thumb`), and an id that resolved to nothing — a deleted account — still
 * links, showing a shortened id so the row stays actionable.
 *
 * The name is capped in **pixels**, not characters. `truncate` was already
 * here and did nothing, because a `table-auto` column grows to fit its widest
 * cell — so one long name stretched the whole table sideways and every other
 * column with it. Counting characters would not have helped either: the
 * longest names in production are 64 characters of cuneiform (`𒐫`) and Syloti
 * Nagri, glyphs several times wider than Latin at the same size. Nothing is
 * lost to the cap — the full name is in `title`.
 */

import { Link } from "react-router-dom";

import { Thumb } from "@/components/Thumb";
import type { UserRefData } from "@/lib/useAdminRefs";

export function UserRef({
  id,
  data,
  size = 20,
  className,
  nameClassName = "max-w-[220px]",
}: {
  id: string;
  data: UserRefData | undefined;
  size?: number;
  className?: string;
  /** Width cap for the name. Overridable for a surface with room to spare —
   *  pass `"max-w-none"` to opt out entirely. */
  nameClassName?: string;
}) {
  const name = data?.name ?? `${id.slice(0, 8)}…`;
  return (
    <Link
      to={`/customers/${id}`}
      title={data?.name ?? id}
      onClick={(e) => {
        // Rows are often clickable themselves; without this the row navigation
        // wins and the link silently goes somewhere else.
        e.stopPropagation();
      }}
      className={`inline-flex min-w-0 items-center gap-1.5 underline-offset-2 hover:underline ${className ?? ""}`}
    >
      <Thumb src={data?.photo_url} name={name} size={size} />
      <span className={`truncate ${nameClassName}`}>{name}</span>
    </Link>
  );
}
