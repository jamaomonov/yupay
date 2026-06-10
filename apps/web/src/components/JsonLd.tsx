import { serializeJsonLd } from "@yupay/utils";

/**
 * Injects a JSON-LD <script> into the page. Server component — the payload is
 * serialised at render time. Keep payloads small and defensible (no invented
 * ratings) so structured data stays trustworthy. Serialisation escapes `<` so
 * API-sourced strings (brand names, FAQ answers) cannot close the tag.
 */
export function JsonLd({ data }: { data: Record<string, unknown> }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: serializeJsonLd(data) }}
    />
  );
}
