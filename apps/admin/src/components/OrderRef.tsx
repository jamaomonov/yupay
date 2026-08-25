/**
 * An order, as a link: what was in it, then its id.
 *
 * The artwork of the first line is what an operator remembers about an order —
 * "the Free Fire one", not `01a0367b-…`. The id stays because it is what gets
 * pasted into a ticket; the picture is what makes the row recognisable without
 * reading it.
 *
 * A wallet deposit has no items and therefore no artwork; it falls back to the
 * initial of its label, which is how it reads as "not a purchase" at a glance.
 */

import { CopyId } from "@/components/CopyId";
import { Thumb } from "@/components/Thumb";
import type { OrderRefData } from "@/lib/useAdminRefs";

export function OrderRef({
  id,
  data,
  size = 20,
  className,
}: {
  id: string;
  data: OrderRefData | undefined;
  size?: number;
  className?: string;
}) {
  return (
    // The label rides as a tooltip rather than as text: in a table row it would
    // be the longest thing on the line, and the picture is already the answer
    // to "what was this order".
    <span
      className={`inline-flex min-w-0 items-center gap-1.5 ${className ?? ""}`}
      title={data?.label ?? undefined}
    >
      <Thumb src={data?.image_url} name={data?.label ?? "?"} size={size} />
      <CopyId value={id} to={`/orders/${id}`} />
    </span>
  );
}
