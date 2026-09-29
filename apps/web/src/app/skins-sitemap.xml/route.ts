import { skinsEnabled } from "@/lib/features";
import {
  chunkCount,
  chunkUrl,
  fetchSkinSlugs,
  sitemapIndexXml,
  today,
  xmlResponse,
} from "@/lib/skins-sitemap";

/** Rebuilt hourly: the item count moves as the market does. */
export const revalidate = 3600;

/** The CS2 skins sitemap index: one file per 5000 items, and the landing pages. */
export async function GET(): Promise<Response> {
  if (!skinsEnabled()) return new Response("Not found", { status: 404 });
  const { total } = await fetchSkinSlugs(0, 1);
  const files = Array.from({ length: chunkCount(total) }, (_, n) => chunkUrl(String(n)));
  return xmlResponse(sitemapIndexXml([...files, chunkUrl("landings")], today()));
}
