# Runbook — media delivery via `cdn.yupay.uz`

Public media (brand logos, hero images, anything uploaded through
`modules/storage`) is served from the R2 bucket `yupay-media` through the custom
domain **`cdn.yupay.uz`**. The API builds every public URL by prefixing
`R2_PUBLIC_BASE_URL` (`modules/storage/service.py`), so the delivery host is one
env var, not a code change.

Live since **2026-07-20**. ADR-0018 chose this shape; until that date the stack
ran on the fallback described below.

## Do not serve production media from `pub-*.r2.dev`

R2 hands every bucket a `pub-<hash>.r2.dev` URL. It is a **development**
endpoint: Cloudflare rate-limits it and documents it as unsuitable for
production traffic. We ran on it for a while and the symptom was subtle — hero
images intermittently failed to appear, most often the below-the-fold ones,
because `next/image` lazy-loads them and they were the requests most likely to
be throttled. Nothing showed up as an error: the DB rows were right, the objects
returned 200 to a single curl, and a fresh browser session rendered fine.

If images "sometimes don't load" and everything else checks out, verify the host
in the URL before hunting for bugs in the app.

## Prerequisite: the zone lives in Cloudflare

An R2 custom domain requires Cloudflare to be authoritative for the zone — it
provisions the CNAME and the certificate itself. `yupay.uz` was moved from
`ahost.uz` to Cloudflare on 2026-07-20 for exactly this reason.

Existing records (`yupay.uz`, `www`, `api`, `admin`) are deliberately kept
**DNS only (grey cloud)**: Cloudflare answers DNS, traffic still goes straight to
the VPS, and Caddy keeps terminating TLS. Only `cdn` is proxied. Turning the
site records orange is a separate decision — it would put Cloudflare in front of
Caddy and change how the real client IP arrives (see the XFF handling in
`infra/edge/Caddyfile`).

### The delegation gap — expect a short outage window

Moving nameservers is not seamless. `ahost` stopped answering for the zone as
soon as the panel change was saved, but the `.uz` registry still delegated to
its servers for a while. In between, the domain failed to resolve: the old
servers were silent and the new ones weren't yet authoritative. It cleared on
its own once the registry published the Cloudflare nameservers.

Plan for it: do the switch in a low-traffic window, and when checking, query the
`.uz` TLD servers directly rather than trusting a public resolver's cache.

```sh
# who does the registry say is authoritative?
dig @$(dig +short ns1.uz A | head -1) yupay.uz NS +noall +authority +answer

# what will Cloudflare serve once delegation lands? (works before propagation)
dig @desiree.ns.cloudflare.com yupay.uz A
```

## Connecting the domain

Cloudflare dashboard → **R2** → bucket `yupay-media` → **Settings** →
**Custom Domains** → **Connect Domain** → `cdn.yupay.uz`. The CNAME and
certificate are created automatically (1–3 min).

Not to be confused with **Allow Access / r2.dev subdomain** in the same panel —
that is the rate-limited endpoint we are moving away from.

## Switching the app over

1. Point the API at the new host and recreate the containers. `docker compose
restart` does **not** re-read `env_file` — only `up -d` does.

   ```sh
   cd /home/ubuntu/opt/yupay
   sudo cp secrets/api.env secrets/api.env.bak-cdn          # keep a way back
   sudo sed -i 's|^R2_PUBLIC_BASE_URL=.*|R2_PUBLIC_BASE_URL=https://cdn.yupay.uz|' secrets/api.env
   docker compose -f docker-compose.prod.yml up -d api worker scheduler bot
   docker compose -f docker-compose.prod.yml exec -T api printenv R2_PUBLIC_BASE_URL
   ```

2. Rewrite URLs already stored in the DB. The env var only shapes **new**
   uploads; rows written earlier keep their absolute host.

   ```sql
   BEGIN;
   UPDATE brands SET logo_url = replace(logo_url,
          'https://pub-<hash>.r2.dev', 'https://cdn.yupay.uz')
    WHERE logo_url LIKE '%r2.dev%';
   UPDATE brands SET hero_image_url = replace(hero_image_url,
          'https://pub-<hash>.r2.dev', 'https://cdn.yupay.uz')
    WHERE hero_image_url LIKE '%r2.dev%';
   COMMIT;
   ```

   Other media columns exist (`products.image_url`, `skus.image_url`,
   `categories.icon`, `users.photo_url`) — check them too; at the time of the
   migration only the brand columns held R2 URLs.

The switch is safe to do live: the old `r2.dev` URLs keep working, so pages
rendered from either host stay intact while it propagates.

## Verifying

```sh
# the domain answers and serves a real object
curl -sI https://cdn.yupay.uz/<key> | head -3

# Cloudflare is caching it (expect cf-cache-status: HIT on the second call)
curl -sI https://cdn.yupay.uz/<key> | grep -i 'cf-cache-status\|cache-control'

# nothing left on the dev endpoint
psql -c "SELECT count(*) FROM brands WHERE logo_url LIKE '%r2.dev%'
                                        OR hero_image_url LIKE '%r2.dev%';"

# the storefront hands out the new host
curl -s https://yupay.uz/ru/store | grep -oE 'https://(cdn\.yupay\.uz|pub-[a-z0-9]+\.r2\.dev)' | sort | uniq -c
```

## Rolling back

Put the old value back in `secrets/api.env`, `up -d` again, and run the same
`UPDATE` with the arguments to `replace()` swapped. The `r2.dev` endpoint stays
enabled on the bucket, so this works at any time — which is the reason not to
disable it the same day the custom domain goes live.

## Related

- ADR-0018 — why R2, presigned uploads, and a custom domain.
- `docs/runbooks/deploy-shared-vps.md` — the host, Caddy, and the shared edge.
