/**
 * Shared pieces of the generated link previews (`/og/...`), 1200×630.
 *
 * A chat app shows one picture under a shared link; a raw game hero said
 * nothing about who sells it or for how much. These cards put the YuPay
 * wordmark, the thing being sold and its starting price in soʻm on it —
 * the same layout as the blog covers.
 *
 * Everything the card draws is read here, not fetched by Satori: fonts and
 * marks from disk once per process, remote art through our own image
 * optimizer, because Satori cannot decode WebP (most brand heroes are WebP)
 * and the optimizer hands JPEG to a client that does not accept WebP. A
 * failed or slow image is dropped, never a failed card.
 */

import { readFile } from "node:fs/promises";
import { join } from "node:path";

import type { ReactNode } from "react";

export const OG_SIZE = { width: 1200, height: 630 } as const;

export const LIME = "#c6f432";
export const BG = "#0b0d12";

const ASSETS = join(process.cwd(), "assets", "og");
const PUBLIC = join(process.cwd(), "public");

/** How long one remote image may hold the card up. */
const IMAGE_TIMEOUT_MS = 4000;

interface OgAssets {
  fonts: { name: string; data: Buffer; weight: 600 | 900; style: "normal" }[];
  wordmark: string;
  payMarks: string[];
}

let assets: Promise<OgAssets> | null = null;

function dataUri(type: string, bytes: Buffer): string {
  return `data:${type};base64,${bytes.toString("base64")}`;
}

async function loadAssets(): Promise<OgAssets> {
  const [unbounded, inter, wordmark, ...marks] = await Promise.all([
    readFile(join(ASSETS, "Unbounded-Black.ttf")),
    readFile(join(ASSETS, "Inter-SemiBold.ttf")),
    readFile(join(PUBLIC, "logo", "wordmark.svg")),
    ...["click", "payme", "uzum"].map((m) => readFile(join(PUBLIC, "payment", `${m}-mark.png`))),
  ]);
  return {
    fonts: [
      { name: "Unbounded", data: unbounded, weight: 900, style: "normal" },
      { name: "Inter", data: inter, weight: 600, style: "normal" },
    ],
    wordmark: dataUri("image/svg+xml", wordmark),
    payMarks: marks.map((m) => dataUri("image/png", m)),
  };
}

/** Fonts and marks, read from disk once per process. */
export function ogAssets(): Promise<OgAssets> {
  assets ??= loadAssets().catch((err: unknown) => {
    assets = null;
    throw err;
  });
  return assets;
}

/**
 * A remote image as a JPEG/PNG data URI, or `null`.
 *
 * Goes through this server's own `/_next/image`, which already allows the
 * hosts our catalogue art lives on and converts WebP for a client that only
 * accepts JPEG. `width` must be one of Next's configured sizes.
 */
export async function remoteImage(url: string | null | undefined, width: number) {
  if (!url) return null;
  const origin = `http://127.0.0.1:${process.env.PORT ?? "3000"}`;
  const src = `${origin}/_next/image?url=${encodeURIComponent(url)}&w=${String(width)}&q=80`;
  try {
    const res = await fetch(src, {
      headers: { accept: "image/jpeg,image/png" },
      signal: AbortSignal.timeout(IMAGE_TIMEOUT_MS),
      cache: "no-store",
    });
    if (!res.ok) return null;
    const type = res.headers.get("content-type") ?? "";
    if (type !== "image/jpeg" && type !== "image/png") return null;
    return dataUri(type, Buffer.from(await res.arrayBuffer()));
  } catch {
    return null;
  }
}

/** Response headers for a card: a shared link is fetched by many chat clients. */
export const OG_HEADERS = {
  "Cache-Control": "public, max-age=3600, s-maxage=3600, stale-while-revalidate=86400",
};

/**
 * A soft colour glow centred at (`x`%, `y`%) of the card.
 *
 * Drawn on a full-card layer on purpose: Satori ignores `closest-side`, so a
 * radial gradient on a smaller box ends in that box's hard edge.
 */
export function Glow({
  x,
  y,
  color,
  reach,
}: {
  x: number;
  y: number;
  color: string;
  reach: number;
}) {
  return (
    <div
      style={{
        // Explicit box: Satori does not size an absolute element from `inset`.
        position: "absolute",
        left: 0,
        top: 0,
        width: OG_SIZE.width,
        height: OG_SIZE.height,
        display: "flex",
        background: `radial-gradient(circle at ${String(x)}% ${String(y)}%, ${color} 0%, rgba(11,13,18,0) ${String(reach)}%)`,
      }}
    />
  );
}

/**
 * The wordmark (top left) and the acquirer marks (bottom left), over `children`.
 *
 * `backdrop` (full-bleed art) goes under the green glow, `children` over it,
 * so the glow tints the art's edge instead of ending against it.
 */
export function OgFrame({
  wordmark,
  payMarks,
  backdrop,
  children,
}: {
  wordmark: string;
  payMarks: string[];
  backdrop?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        width: OG_SIZE.width,
        height: OG_SIZE.height,
        display: "flex",
        position: "relative",
        background: BG,
        color: "#fff",
        fontFamily: "Inter",
      }}
    >
      {backdrop}
      <Glow x={12} y={72} color="rgba(70,150,30,.45)" reach={40} />
      {children}
      {/* eslint-disable-next-line @next/next/no-img-element -- Satori draws <img>, not next/image */}
      <img
        src={wordmark}
        width={200}
        height={61}
        style={{ position: "absolute", left: 48, top: 44 }}
        alt=""
      />
      <div style={{ position: "absolute", left: 48, bottom: 44, display: "flex", gap: 14 }}>
        {payMarks.map((src) => (
          <div
            key={src.length}
            style={{
              width: 58,
              height: 48,
              borderRadius: 12,
              background: "#161a22",
              border: "1px solid #232835",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- Satori */}
            <img src={src} width={36} height={36} style={{ borderRadius: 6 }} alt="" />
          </div>
        ))}
      </div>
    </div>
  );
}

/** The lime starting-price pill. */
export function PriceChip({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        alignSelf: "flex-start",
        background: LIME,
        color: BG,
        fontFamily: "Unbounded",
        fontSize: 34,
        whiteSpace: "nowrap",
        padding: "16px 28px",
        borderRadius: 20,
        boxShadow: "0 0 40px rgba(198,244,50,.35)",
      }}
    >
      {children}
    </div>
  );
}

/** A display size that keeps a long name on the card. */
export function headlineSize(text: string, sizes: [number, number, number]): number {
  if (text.length <= 10) return sizes[0];
  if (text.length <= 18) return sizes[1];
  return sizes[2];
}
