/** Manual-fulfilment DTOs — mirror of the backend ``ManualCompleteIn`` /
 * ``ManualFailIn`` shapes. Hand-written for now (the admin SPA doesn't
 * consume the generated client yet — see comment in ``features/fulfillment/types.ts``).
 */

export type ArtifactKind = "voucher_code" | "topup_receipt" | "license_key";
export type DeliveryChannel = "in_app" | "email" | "telegram";

export interface ManualCompleteIn {
  artifact_kind: ArtifactKind;
  artifact: Record<string, unknown>;
  channel?: DeliveryChannel;
  admin_note?: string | null;
}

export interface ManualFailIn {
  reason: string;
  admin_note?: string | null;
}

export const ARTIFACT_KIND_LABEL: Record<ArtifactKind, string> = {
  voucher_code: "Ваучер",
  topup_receipt: "Чек пополнения",
  license_key: "Лицензионный ключ",
};
