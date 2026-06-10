/**
 * Serialize a JSON-LD payload for embedding in a `<script>` tag.
 *
 * `JSON.stringify` escapes quotes but not `<`, so an API-sourced string
 * containing `</script>` would terminate the tag and execute arbitrary HTML.
 * `<` is valid JSON, so the output still parses to the same object.
 */
export function serializeJsonLd(data: Record<string, unknown>): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
