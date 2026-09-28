/** A skin line's Steam trade on the admin order page, with the way to its full record. */

import adminRu from "@yupay/i18n/locales/ru/admin.json";
import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";

import type { OrderItemOut } from "./types";

import { StatusChip } from "@/components/StatusChip";

const L = adminRu.skins.orderLine;

export function SkinTradeLine({
  trade,
  orderId,
}: {
  trade: NonNullable<OrderItemOut["skin_trade"]>;
  orderId: string;
}) {
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
      <StatusChip domain="skinTradeState" value={trade.state} />
      {trade.seller?.name && (
        <span className="text-[var(--text-secondary)]">
          {L.seller.replace("{name}", trade.seller.name)}
        </span>
      )}
      {trade.offer_url && (
        <a
          href={trade.offer_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-[var(--accent)]"
        >
          {L.openOffer}
          <ExternalLink size={12} aria-hidden />
        </a>
      )}
      <Link to={`/skins/trades?q=${encodeURIComponent(orderId)}`} className="text-[var(--accent)]">
        {L.trades}
      </Link>
    </div>
  );
}
