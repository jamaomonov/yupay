import { getTranslations } from "next-intl/server";

import { Skeleton } from "@/components/ui/Skeleton";

/**
 * Brand-page placeholder — hero, denomination grid and the order panel beside
 * it, in the proportions the real page uses, so the layout doesn't jump when
 * the data lands.
 */
export default async function BrandLoading() {
  const t = await getTranslations("web.common");
  return (
    <main className="relative min-h-screen pb-28 pt-[120px]" aria-busy="true">
      <span className="sr-only" role="status">
        {t("loadingTitle")}
      </span>
      <div className="mx-auto max-w-[1100px] px-6 sm:px-10">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="mt-6 h-12 w-72" />
        <Skeleton className="mt-4 h-5 w-full max-w-[36rem]" />
        <div className="mt-10 grid grid-cols-1 gap-8 lg:grid-cols-[1fr_380px]">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-[132px] rounded-lg" />
            ))}
          </div>
          <Skeleton className="h-[420px] rounded-xl" />
        </div>
      </div>
    </main>
  );
}
