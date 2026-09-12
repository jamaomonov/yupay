import { Eye, Heart } from "lucide-react";
import { getTranslations } from "next-intl/server";

interface Props {
  likes: number;
  views: number;
}

export async function EngagementStats({ likes, views }: Props) {
  const t = await getTranslations("web.blog");
  return (
    <div className="text-tx-dim flex items-center gap-3 font-mono text-[11px]">
      <span
        className="inline-flex items-center gap-1"
        aria-label={t("viewsAria", { count: views })}
      >
        <Eye size={12} aria-hidden />
        {views}
      </span>
      <span
        className="inline-flex items-center gap-1"
        aria-label={t("likesAria", { count: likes })}
      >
        <Heart size={12} aria-hidden />
        {likes}
      </span>
    </div>
  );
}
