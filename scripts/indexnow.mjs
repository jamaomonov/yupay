#!/usr/bin/env node
/**
 * IndexNow submitter — pings Bing/Yandex (NOT Google; Google doesn't support
 * IndexNow) with the storefront's public URLs so they recrawl on demand.
 *
 * Ownership is proven by a key file hosted at `${SITE}/${KEY}.txt` whose body is
 * the key itself (see apps/web/public/<key>.txt). Run after a deploy that
 * changes content:
 *
 *   node scripts/indexnow.mjs                       # reads urls from the sitemap
 *   INDEXNOW_URLS="https://yupay.uz/store" node scripts/indexnow.mjs   # specific
 *
 * Env: SITE (default https://yupay.uz), INDEXNOW_KEY (default = the committed
 * key), INDEXNOW_ENDPOINT (default https://api.indexnow.org/indexnow).
 */

const SITE = (process.env.SITE ?? "https://yupay.uz").replace(/\/$/, "");
const KEY = process.env.INDEXNOW_KEY ?? "f9c74a83b42e048f6273ce96100f14dd";
const ENDPOINT = process.env.INDEXNOW_ENDPOINT ?? "https://api.indexnow.org/indexnow";
const HOST = new URL(SITE).host;

/** Pull every <loc> from the deployed sitemap. */
async function urlsFromSitemap() {
  const res = await fetch(`${SITE}/sitemap.xml`, { headers: { "user-agent": "yupay-indexnow" } });
  if (!res.ok) throw new Error(`sitemap fetch failed: ${res.status}`);
  const xml = await res.text();
  return [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1].trim());
}

async function main() {
  const override = process.env.INDEXNOW_URLS?.split(/[\s,]+/).filter(Boolean);
  const urlList = override?.length ? override : await urlsFromSitemap();
  if (urlList.length === 0) throw new Error("no URLs to submit");

  // Sanity: the key file must be reachable, or IndexNow rejects the batch.
  const keyRes = await fetch(`${SITE}/${KEY}.txt`);
  if (!keyRes.ok || (await keyRes.text()).trim() !== KEY) {
    throw new Error(
      `key file ${SITE}/${KEY}.txt is not serving the key (status ${keyRes.status}) — deploy the web app first`,
    );
  }

  const body = { host: HOST, key: KEY, keyLocation: `${SITE}/${KEY}.txt`, urlList };
  const res = await fetch(ENDPOINT, {
    method: "POST",
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify(body),
  });
  // IndexNow returns 200/202 on success; 4xx on key/host problems.
  console.log(
    `IndexNow ${res.status} ${res.statusText} — submitted ${urlList.length} URL(s) for ${HOST}`,
  );
  if (!res.ok && res.status !== 202) {
    console.error(await res.text());
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(err.message ?? err);
  process.exit(1);
});
