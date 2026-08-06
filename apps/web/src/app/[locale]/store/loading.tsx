import { getTranslations } from "next-intl/server";

import { Skeleton } from "@/components/ui/Skeleton";

/**
 * Catalogue placeholder.
 *
 * Brand pages are ISR'd, so a cold segment can take a moment to stream. Until
 * now nothing filled that gap: the previous route stayed on screen with no
 * feedback, which reads as a dead tap rather than as loading. The shape mirrors
 * the real grid so nothing jumps when the content lands.
 */
export default async function StoreLoading() {
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
        <div className="mt-10 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-[220px] rounded-[20px]" />
          ))}
        </div>
      </div>
    </main>
  );
}
