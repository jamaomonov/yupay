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
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

/** The create call's answer: the one moment the secret is readable. */
export interface IssuedKey {
  key_id: string;
  secret: string;
  label: string;
  created_at: string;
}
