import createNextIntlPlugin from "next-intl/plugin";

import type { NextConfig } from "next";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  typedRoutes: true,
  // Lint runs separately via `make lint` / CI — the same reason apps/web gives.
  eslint: { ignoreDuringBuilds: true },
  images: {
    // Our own hosts only. Third-party catalog art is drawn with a plain <img>
    // (see the catalog's Logo), so nothing needs the optimizer to fetch it —
    // and a `hostname: "**"` entry made /_next/image an open fetch-anything
    // proxy (audit 2026-11-10), the catch-all apps/web dropped for the same reason.
    remotePatterns: [
      { protocol: "https", hostname: "**.yupay.uz" },
      { protocol: "https", hostname: "*.r2.dev" },
    ],
  },
  transpilePackages: ["@yupay/ui", "@yupay/i18n", "@yupay/utils"],
};

export default withNextIntl(nextConfig);
