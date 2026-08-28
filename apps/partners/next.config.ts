import createNextIntlPlugin from "next-intl/plugin";

import type { NextConfig } from "next";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  typedRoutes: true,
  // Lint runs separately via `make lint` / CI, the same as the storefront.
  eslint: { ignoreDuringBuilds: true },
  // No `images` block: this site renders no remote imagery. The storefront
  // needs a broad https allowlist because admins paste third-party catalog
  // URLs; nothing here does, so it gets no remote-image surface at all.
  transpilePackages: ["@yupay/ui", "@yupay/api-client", "@yupay/i18n", "@yupay/utils"],
};

export default withNextIntl(nextConfig);
