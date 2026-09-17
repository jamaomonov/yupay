import createNextIntlPlugin from "next-intl/plugin";

import type { NextConfig } from "next";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
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
      { protocol: "https", hostname: "**.yupay.uz" },
      { protocol: "https", hostname: "cdn.yupay.uz" },
      // R2 bucket fallback when the cdn.yupay.uz custom domain isn't wired
      // up in a given environment (see the R2_PUBLIC_BASE_URL comment).
      { protocol: "https", hostname: "*.r2.dev" },
      // Catalog brand/product/SKU art also comes from admin-pasted
      // third-party CDN URLs with no fixed, enumerable host list — see
      // apps/admin/src/components/ImageUploader.tsx ("Catalog images often
      // live on third-party hosts (legacy URLs)"). There is no glob that
      // means "any public https host but not a private/internal one" (that
      // needs IP-space knowledge Next's config layer doesn't have), so this
      // stays a broad https catch-all rather than a curated allowlist that
      // would silently break images we can't inventory from here.
      //
      // SSRF: the actual gate against this being used to reach internal
      // infra is the backend validator
      // (apps/api/src/yupay/modules/catalog/image_url_safety.py
      // validate_public_image_url), applied to every
      // image_url/logo_url/hero_image_url at write time — admin
      // create/update AND the G2B import — which rejects IP-literal
      // loopback/private/link-local/metadata targets and
      // localhost/*.local/*.internal before a URL is ever persisted. By
      // the time this config decides whether to fetch a URL, it has
      // already passed that check. Residual risk (documented on the
      // validator too): DNS rebinding — a hostname that resolves to a
      // public IP when validated but a private one when fetched — is not
      // and cannot be closed by either layer.
      { protocol: "https", hostname: "**" },
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
