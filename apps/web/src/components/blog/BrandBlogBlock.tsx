import { getTranslations } from "next-intl/server";

import { BlogPostCard } from "./BlogPostCard";

import { listBrandPosts } from "@/lib/blog";

export async function BrandBlogBlock({
  brandSlug,
  brandName,
  locale,
}: {
  brandSlug: string;
  brandName: string;
  locale: string;
}) {
  let items: Awaited<ReturnType<typeof listBrandPosts>> = [];
  try {
    items = await listBrandPosts(brandSlug, locale);
  } catch {
    return null;
  }
  if (items.length === 0) return null;
  const t = await getTranslations("web.blog");

  return (
    <section className="mt-16">
      <h2 className="font-display text-xl font-bold tracking-[-0.02em]">
        {t("brandBlockTitle", { name: brandName })}
      </h2>
      <div className="mt-5 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((post) => (
          <BlogPostCard key={post.id} post={post} locale={locale} />
        ))}
      </div>
    </section>
  );
}
