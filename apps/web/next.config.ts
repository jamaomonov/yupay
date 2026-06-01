import createNextIntlPlugin from "next-intl/plugin";

import type { NextConfig } from "next";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  typedRoutes: true,
  // Lint runs separately via `make lint` / CI. Don't gate Docker builds on ESLint —
  // it duplicates work and conflates lint failures with build failures.
  eslint: { ignoreDuringBuilds: true },
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**.yupay.io" },
      { protocol: "https", hostname: "cdn.yupay.io" },
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
