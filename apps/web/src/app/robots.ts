import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: ["/api/", "/admin/"] }],
    sitemap: "https://app.yupay.uz/sitemap.xml",
    host: "https://app.yupay.uz",
  };
}
