/**
 * Direct-to-R2 upload used by catalogue images and the blog editor.
 * Handshake is ADR-0018: presign, then PUT, persist the public URL.
 */

import { apiPost } from "@/lib/api";

export type RasterMediaKind =
  | "brand_logo"
  | "brand_hero"
  | "product_image"
  | "sku_image"
  | "blog_image";

interface PresignOut {
  upload_url: string;
  public_url: string;
}

const ACCEPT = new Set(["image/png", "image/jpeg", "image/webp"]);
const MAX_BYTES = 5 * 1024 * 1024;

export function assertRasterImage(file: File): void {
  if (!ACCEPT.has(file.type)) {
    throw new Error("Только PNG / JPEG / WebP.");
  }
  if (file.size > MAX_BYTES) {
    throw new Error(`Файл больше ${(MAX_BYTES / 1024 / 1024).toString()} MB.`);
  }
}

export async function uploadRasterMedia(kind: RasterMediaKind, file: File): Promise<string> {
  assertRasterImage(file);
  const presign = await apiPost<PresignOut>("/api/v1/admin/media/presign-upload", {
    kind,
    content_type: file.type,
    size_bytes: file.size,
  });
  const putRes = await fetch(presign.upload_url, {
    method: "PUT",
    headers: { "Content-Type": file.type },
    body: file,
  });
  if (!putRes.ok) {
    throw new Error(`R2 upload failed: ${putRes.status.toString()} ${putRes.statusText}`);
  }
  return presign.public_url;
}
