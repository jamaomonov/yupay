import createNextIntlPlugin from "next-intl/plugin";

import type { NextConfig } from "next";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  // iOS Safari requests these two paths on every visit regardless of the
  // <link rel="apple-touch-icon"> we publish. Neither file exists, and a path
  // with a dot bypasses the i18n middleware, so they fell into the `[locale]`
  // route as the locale `apple-touch-icon.png` — a 500 per visit. Point them
  // at the icon the app router already serves from `app/apple-icon.png`.
  async redirects() {
    return [
      { source: "/apple-touch-icon.png", destination: "/apple-icon.png", permanent: true },
      {
        source: "/apple-touch-icon-precomposed.png",
        destination: "/apple-icon.png",
        permanent: true,
      },
    ];
  },
  reactStrictMode: true,
  typedRoutes: true,
  // Lint runs separately via `make lint` / CI. Don't gate Docker builds on ESLint —
  // it duplicates work and conflates lint failures with build failures.
  eslint: { ignoreDuringBuilds: true },
  experimental: {
    // Prerendering fetches the **deployed** API for some 200 brand and blog
    // pages, so one slow reply from `api.yupay.uz` ended the whole production
    // build with `ETIMEDOUT` and left no image at all — which is how the
    // 2026-09-17 reseller deploy became a two-step affair. So: give a page
    // another go before failing the build on it, and hold fewer sockets open
    // at once (Next's default is 8). A build is a burst of traffic against our
    // own API and it is not in a hurry; a build that dies on one blip is.
    staticGenerationRetryCount: 3,
    staticGenerationMaxConcurrency: 4,
  },
  images: {
    remotePatterns: [
      // First-party: the storefront domain itself + the R2-backed CDN
      // (infra/secrets-example/api.env R2_PUBLIC_BASE_URL, wired through
      // apps/api/.../storage/service.py public_url_for()). The prod domain
      // is yupay.uz (see infra/caddy/Caddyfile.prod) — these two entries
      // used to say ".yupay.io", which doesn't match any deployed host.
      { protocol: "https", hostname: "yupay.uz" },
      { protocol: "https", hostname: "**.yupay.uz" },
      { protocol: "https", hostname: "cdn.yupay.uz" },
      // R2 bucket fallback when the cdn.yupay.uz custom domain isn't wired
      // up in a given environment (see the R2_PUBLIC_BASE_URL comment).
      { protocol: "https", hostname: "*.r2.dev" },
      // Public third-party image CDNs we render: Steam (skins, game art,
      // avatars), Google and Telegram profile photos. Every <Image> with a
      // third-party src already passes `unoptimized` (lib/image.ts
      // isOptimizable), so the browser fetches these directly and the
      // optimizer never sees them; they are listed only so a component that
      // forgets the flag degrades to a public CDN fetch, not a 400.
      { protocol: "https", hostname: "**.steamstatic.com" },
      { protocol: "https", hostname: "steamcdn-a.akamaihd.net" },
      { protocol: "https", hostname: "steamcommunity-a.akamaihd.net" },
      { protocol: "https", hostname: "lh3.googleusercontent.com" },
      { protocol: "https", hostname: "t.me" },
      // No `hostname: "**"` catch-all. It used to be here on the theory that
      // only DB-persisted, write-time-validated URLs reach the optimizer —
      // false: `/_next/image?url=` takes any URL from the query string, so
      // the catch-all made the web container an open fetch proxy (a scanner
      // aimed it at https://redis, rabbitmq, 127.0.0.1 and 10.0.0.1 on
      // 2026-11-03). A new image host is a new line here, never a wildcard.
    ],
    // Brand marks + wordmark are first-party SVGs we control. Allow the image
    // optimizer to serve them, sandboxed so they can't execute scripts.
    dangerouslyAllowSVG: true,
    contentDispositionType: "attachment",
    contentSecurityPolicy: "default-src 'self'; script-src 'none'; sandbox;",
  },
  transpilePackages: [
    "@yupay/ui",
    "@yupay/api-client",
    "@yupay/i18n",
    "@yupay/telegram",
    "@yupay/utils",
    "@yupay/analytics",
  ],
};

export default withNextIntl(nextConfig);
