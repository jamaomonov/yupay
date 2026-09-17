import { serializeJsonLd } from "@yupay/utils";

/**
 * Injects a JSON-LD <script> into the page. Server component — the payload is
 * serialised at render time. Keep payloads small and defensible (no invented
 * ratings) so structured data stays trustworthy. Serialisation escapes `<` so
 * API-sourced strings cannot close the tag. Same component as the
 * storefront's `apps/web/src/components/JsonLd.tsx`.
 */
export function JsonLd({ data }: { data: Record<string, unknown> }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: serializeJsonLd(data) }}
    />
  );
}
