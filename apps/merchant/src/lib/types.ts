/** Shapes the cabinet reads from the BFF. Mirrors the API's response models. */

export interface Profile {
  user_id: string;
  email: string;
  timezone: string;
  merchant_id: string;
  title: string;
  status: string;
  balance_usd: string;
  offer_version: string | null;
  offer_accepted_at: string | null;
}

/** One purchasable line. `kind` says which of the price fields is populated. */
export interface Sku {
  sku_id: string;
  sku_code: string;
  name: string;
  kind: "fixed" | "unit" | "amount";
  price_usd: string | null;
  /** Our storefront price for the same thing — the crossed-out reference. */
  retail_price_usd: string | null;
  unit_price_usd: string | null;
  unit: string | null;
  min_qty: number | null;
  max_qty: number | null;
  min_amount_usd: string | null;
  max_amount_usd: string | null;
  updated_at: string;
}

/** One input a product's `fulfillment_data` expects. */
export interface Field {
  key: string;
  type: string;
  required: boolean;
  label: Record<string, string>;
  placeholder: Record<string, string>;
  pattern: string | null;
}

export interface Product {
  product_id: string;
  slug: string;
  name: string;
  required_fields: Field[];
  skus: Sku[];
}

export interface Brand {
  brand_id: string;
  slug: string;
  name: string;
  products: Product[];
}

export interface Catalog {
  brands: Brand[];
}

export interface PlacedOrder {
  merchant_order_id: string;
  order_id: string;
  status: string;
  sku_id: string;
  price_usd: string;
  balance_usd: string;
  created_at: string;
}

/** One line of the Orders list. Money is the ledger's, not the order line's. */
export interface OrderRow {
  merchant_order_id: string;
  order_id: string;
  status: string;
  sku_code: string;
  price_usd: string;
  refunded_usd: string;
  created_at: string;
  delivered_at: string | null;
}

export interface OrdersPage {
  items: OrderRow[];
  next_cursor: string | null;
}

/** What a delivered order handed over. `artifact`'s shape follows its kind. */
export interface Delivery {
  artifact_kind: string;
  artifact: Record<string, unknown>;
  delivered_at: string;
}

export interface OrderEvent {
  event: string;
  at: string;
}

export interface OrderDetail {
  merchant_order_id: string;
  order_id: string;
  status: string;
  sku_id: string;
  price_usd: string;
  refunded_usd: string;
  created_at: string;
  paid_at: string | null;
  delivered_at: string | null;
  failure_reason: string | null;
  delivery: Delivery | null;
  timeline: OrderEvent[];
}

/** One movement of the deposit. `amount_usd` is signed. */
export interface Transaction {
  transaction_id: string;
  kind: string;
  amount_usd: string;
  order_id: string | null;
  merchant_order_id: string | null;
  created_at: string;
}

export interface TransactionsPage {
  items: Transaction[];
  next_cursor: string | null;
}

/** A machine credential as Settings lists it — never with its secret. */
export interface ApiKey {
  id: string;
  key_id: string;
  label: string;
  ip_allowlist: string[] | null;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

/** The create call's answer: the one moment the secret is readable. */
export interface IssuedKey {
  key_id: string;
  secret: string;
  label: string;
  ip_allowlist: string[] | null;
  created_at: string;
}

/** The configured endpoint and how it has been behaving. */
export interface Webhook {
  url: string;
  disabled_at: string | null;
  failure_streak: number;
  last_success_at: string | null;
  last_failure_at: string | null;
  created_at: string;
  updated_at: string;
}

/** What a call that could mint a signing secret answers. `null` when it did not. */
export interface WebhookWithSecret extends Webhook {
  secret: string | null;
}

/** One attempted delivery. `url` is where it went, snapshotted at enqueue. */
export interface WebhookDelivery {
  id: string;
  event_type: string;
  url: string;
  status: string;
  attempts_count: number;
  payload: Record<string, unknown>;
  response_code: number | null;
  response_body: string | null;
  last_error: string | null;
  next_attempt_at: string;
  created_at: string;
  updated_at: string;
}

export interface DeliveriesPage {
  items: WebhookDelivery[];
  next_cursor: string | null;
}

/** The dashboard's three numbers, for a window the browser chose. */
export interface Summary {
  orders: number;
  delivered: number;
  spend_usd: string;
  /** `spend_usd` is a floor: the window held more orders than the API reads. */
  spend_capped: boolean;
}
