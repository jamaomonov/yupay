"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import type { SkinQuery, SkinSort as Sort } from "@/lib/skins";

import { inputStyles } from "@/lib/input";
import { pathFor } from "@/lib/seo";
import { skinQueryString } from "@/lib/skins";

const SORTS: Sort[] = ["-price", "price", "popular", "discount"];

/** The one control that needs JS to feel right: a select that navigates on change. */
export function SkinSort({ query, locale }: { query: SkinQuery; locale: string }) {
  const t = useTranslations("web.skins");
  const router = useRouter();
  return (
    <label className="shrink-0">
      <span className="sr-only">{t("sortLabel")}</span>
      <select
        value={query.sort}
        onChange={(e) => {
          const sort = e.target.value as Sort; // one of SORTS, rendered below
          router.push(pathFor(locale, "/skins") + skinQueryString(query, { sort }));
        }}
        className={inputStyles({ className: "w-auto pr-8 text-[14px] font-semibold" })}
      >
        {SORTS.map((s) => (
          <option key={s} value={s}>
            {t(`sort.${s}`)}
          </option>
        ))}
      </select>
    </label>
  );
}
