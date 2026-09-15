import createNextIntlPlugin from "next-intl/plugin";

import type { NextConfig } from "next";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  typedRoutes: true,
  // Lint runs separately via `make lint` / CI — the same reason apps/web gives.
  eslint: { ignoreDuringBuilds: true },
  images: {
    // Brand art only, and it comes from the same places the storefront's does:
    // our own CDN, the R2 bucket behind it, and the third-party hosts admins
    // paste catalog URLs from. The SSRF gate is the backend validator at write
    // time (`catalog.image_url_safety`), not this list — see apps/web's config
    // for the full reasoning, which applies here unchanged.
    remotePatterns: [
      { protocol: "https", hostname: "**.yupay.uz" },
      { protocol: "https", hostname: "cdn.yupay.uz" },
      { protocol: "https", hostname: "*.r2.dev" },
      { protocol: "https", hostname: "**" },
    ],
  },
  transpilePackages: ["@yupay/ui", "@yupay/i18n", "@yupay/utils"],
};

export default withNextIntl(nextConfig);
