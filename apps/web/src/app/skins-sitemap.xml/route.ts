import { skinsEnabled } from "@/lib/features";
import {
  chunkCount,
  chunkUrl,
  fetchSkinSlugs,
  sitemapIndexXml,
  today,
  xmlResponse,
} from "@/lib/skins-sitemap";

/**
 * Per request: `SKINS_ENABLED` lives in the web env at runtime, and a render baked at
 * build (flag off in CI) answered 404 on prod. The API read is still cached an hour.
 */
export const dynamic = "force-dynamic";

/** The CS2 skins sitemap index: one file per 5000 items, and the landing pages. */
export async function GET(): Promise<Response> {
  if (!skinsEnabled()) return new Response("Not found", { status: 404 });
  const { total } = await fetchSkinSlugs(0, 1);
  const files = Array.from({ length: chunkCount(total) }, (_, n) => chunkUrl(String(n)));
  return xmlResponse(sitemapIndexXml([...files, chunkUrl("landings")], today()));
}
