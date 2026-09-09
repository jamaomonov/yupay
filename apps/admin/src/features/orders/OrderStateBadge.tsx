/**
 * The order's status, plus what has actually stopped it.
 *
 * The two are rendered together and never in place of each other, because they
 * answer different questions and only one of them is allowed to move. A
 * terminal fulfilment failure deliberately leaves `order.status` alone —
 * retail's rule: an operator may still top a supplier up, retry, or deliver by
 * hand — so the list read «В работе» on a dead order for ever. Overwriting the
 * badge would make the admin disagree with the FSM; the suffix says the part
 * the FSM does not.
 *
 * The value is the server's, from the same function `/merchant/v1` publishes
 * (`merchants.order_status.order_stop_states`). The admin does not re-derive it:
 * an operator explaining an order to a reseller must be reading the same word
 * the reseller is.
 *
 * An unrecognised value renders as nothing at all — the field's contract is
 * additive and says "treat an unknown one as still in flight", so a build
 * older than the API must stay quiet rather than paint an empty chip.
 */

import { failureReasonLabel, FAILURE_REASON_TONE, STATUS_LABEL, STATUS_TONE } from "./types";
import type { OrderFailureReason, OrderStatus } from "./types";

import { Badge } from "@/components/Badge";

export function OrderStateBadge({
  status,
  failureReason,
}: {
  status: OrderStatus;
  failureReason: string | null;
}) {
  const label = failureReasonLabel(failureReason);
  return (
    <span className="inline-flex flex-wrap items-baseline gap-x-1.5">
      <Badge tone={STATUS_TONE[status]} dot>
        {STATUS_LABEL[status]}
      </Badge>
      {label !== null && (
        <>
          {/* The separator is its own element and `aria-hidden`: it is
              punctuation, it must not be read out between two facts, and it
              must not end up inside the label — the three locales carry words,
              not typography. */}
          <span aria-hidden className="text-xs text-[var(--text-secondary)]">
            ·
          </span>
          <span className={`text-xs ${FAILURE_REASON_TONE[failureReason as OrderFailureReason]}`}>
            {label}
          </span>
        </>
      )}
    </span>
  );
}
