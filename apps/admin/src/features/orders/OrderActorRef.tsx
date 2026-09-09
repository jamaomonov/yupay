/**
 * Who placed an order, rendered — one component for every screen that asks.
 *
 * Orders have had three actor arms since M2 (`ck_orders_actor_exclusive`:
 * user, guest, merchant) and the admin had two. Both the list cell and the
 * detail header spelled the same `guest_email ?? …` fallback, so a B2B order —
 * whose two retail arms are null by construction — read as an anonymous
 * buyer, on both, with only a raw uuid in one timeline payload to say
 * otherwise.
 *
 * The fix is not a third `??`. It is a switch over {@link orderActorOf}'s
 * union with `assertNever` on the default, so a *fourth* arm added to the
 * CHECK is a type error here rather than another silent «Гость».
 *
 * Each arm links where the next question is answered: a person's customer
 * page, a reseller's merchant page (their deposit, their ledger, their API
 * keys). A guest has no page, so their address is the whole answer.
 */

import { Link } from "react-router-dom";

import { orderActorOf, type OrderActorFields } from "./types";

import { UserRef } from "@/components/UserRef";
import type { UserRefData } from "@/lib/useAdminRefs";

import adminRu from "@yupay/i18n/locales/ru/admin.json";
import { assertNever } from "@yupay/utils";

const ACTOR = adminRu.orders.actor;

export function OrderActorRef({
  order,
  user,
  className,
  labelled = false,
}: {
  order: OrderActorFields;
  /** Resolved name/avatar for the `user` arm, from `useAdminRefs`. */
  user?: UserRefData | undefined;
  className?: string;
  /** Prefix each arm with what it is («Пользователь …», «Мерчант …»).
   *  On the detail header there is room for it and it disambiguates a
   *  reseller's title from a person's name; in a narrow table cell it is
   *  noise, and the column header already says «актёр». */
  labelled?: boolean;
}) {
  const actor = orderActorOf(order);
  const muted = `text-[var(--text-secondary)] ${className ?? ""}`;
  switch (actor.kind) {
    case "user":
      return (
        <span className="inline-flex min-w-0 items-center gap-1.5">
          {labelled && <span className="text-[var(--text-secondary)]">{ACTOR.user}</span>}
          <UserRef id={actor.userId} data={user} className={className ?? ""} />
        </span>
      );
    case "guest":
      return <span className={muted}>{actor.email}</span>;
    case "merchant":
      return (
        <span className="inline-flex min-w-0 items-center gap-1.5">
          {labelled && <span className="text-[var(--text-secondary)]">{ACTOR.merchant}</span>}
          <Link
            to={`/merchants/${actor.merchantId}`}
            title={actor.title ?? actor.merchantId}
            onClick={(e) => {
              // Rows are clickable themselves; without this the row navigation
              // wins and the link silently goes to the order instead.
              e.stopPropagation();
            }}
            className={`truncate underline-offset-2 hover:underline ${className ?? ""}`}
          >
            {/* The id when there is no title — which `ON DELETE RESTRICT` on
                `orders.merchant_id` makes unreachable. «Мерчант —» would say
                less than the uuid this change exists to replace. */}
            {actor.title ?? actor.merchantId}
          </Link>
        </span>
      );
    case "none":
      return <span className={muted}>{ACTOR.none}</span>;
    default:
      return assertNever(actor);
  }
}
