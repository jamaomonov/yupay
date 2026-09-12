import { getTranslations } from "next-intl/server";

import { BlogPostCard } from "./BlogPostCard";
import { listBrandPosts } from "@/lib/blog";

export async function RelatedPosts({
  brandSlug,
  brandName,
  excludeSlug,
  locale,
}: {
  brandSlug: string;
  brandName: string;
  excludeSlug: string;
  locale: string;
}) {
  const items = (await listBrandPosts(brandSlug, locale).catch(() => []))
    .filter((post) => post.slug !== excludeSlug)
    .slice(0, 3);
  if (items.length === 0) return null;
  const t = await getTranslations("web.blog");

  return (
    <section className="mt-12">
      <h2 className="font-display text-xl font-semibold tracking-[-0.02em]">
        {t("moreFromBrand", { name: brandName })}
      </h2>
      <div className="mt-5 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((post) => (
          <BlogPostCard key={post.id} post={post} locale={locale} />
        ))}
      </div>
    </section>
  );
}
