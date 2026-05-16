import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Lint runs separately via `make lint` / CI. Don't gate Docker builds on ESLint —
  // it duplicates work and conflates lint failures with build failures.
  eslint: { ignoreDuringBuilds: true },
  images: { unoptimized: true },
  transpilePackages: [
    "@yupay/ui",
    "@yupay/api-client",
    "@yupay/i18n",
    "@yupay/telegram",
    "@yupay/utils",
    "@yupay/analytics",
  ],
};

export default nextConfig;
