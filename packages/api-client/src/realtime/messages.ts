/**
 * Wire format for order-update events delivered over the WebSocket gateway.
 *
 * The server uses a discriminated-union JSON envelope. Add new variants here and in the
 * corresponding Pydantic model in `apps/api/src/yupay/modules/realtime/`.
 */

export type OrderUpdateMessage =
  | { type: "order.status_changed"; orderId: string; status: string; at: string }
  | { type: "order.delivered"; orderId: string; payload: { kind: string; data: unknown } }
  | { type: "order.failed"; orderId: string; reason: string }
  | { type: "ping"; at: string };
