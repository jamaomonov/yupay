import Image from "next/image";

/**
 * yupay wordmark — the real brand lockup (white "yupay" + lime up-arrow as the
 * "u"), shared with the Telegram mini app so web and in-app branding match
 * 1:1. SVG keeps it crisp at any size; intrinsic ratio is ~3.27:1.
 */
export function Wordmark({ size = "md" }: { size?: "sm" | "md" }) {
  const height = size === "sm" ? 24 : 30;
  const width = Math.round(height * 3.27);
  return (
    <Image
      src="/logo/wordmark.svg"
      alt="yupay"
      width={width}
      height={height}
      priority
      style={{ height, width: "auto" }}
    />
  );
}
