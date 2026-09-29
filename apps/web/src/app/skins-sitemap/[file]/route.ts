import { skinsEnabled } from "@/lib/features";
import { landingPaths } from "@/lib/skin-landing";
import { getSkinFacets } from "@/lib/skins";
import {
  fetchSkinSlugs,
  SKINS_PER_SITEMAP,
  today,
  urlsetXml,
  xmlResponse,
} from "@/lib/skins-sitemap";

export const revalidate = 3600;

const NOT_FOUND = () => new Response("Not found", { status: 404 });

/**
 * `/skins-sitemap/<n>.xml`: item pages `n × 5000` onwards, alphabetical;
 * `/skins-sitemap/landings.xml`: the category and weapon landing pages.
 */
export async function GET(
  _req: Request,
  { params }: { params: Promise<{ file: string }> },
): Promise<Response> {
  if (!skinsEnabled()) return NOT_FOUND();
  const { file } = await params;
  if (file === "landings.xml") {
    const facets = await getSkinFacets("ru");
    if (!facets) return NOT_FOUND();
    return xmlResponse(urlsetXml(landingPaths(facets), today()));
  }
  const match = /^(\d{1,3})\.xml$/.exec(file);
  if (!match) return NOT_FOUND();
  const { items } = await fetchSkinSlugs(Number(match[1]) * SKINS_PER_SITEMAP);
  if (items.length === 0) return NOT_FOUND();
  return xmlResponse(
    urlsetXml(
      items.map((slug) => `/skins/${slug}`),
      today(),
    ),
  );
}
