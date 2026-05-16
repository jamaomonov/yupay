import { Button } from "@yupay/ui";
import { setRequestLocale } from "next-intl/server";
import { getTranslations } from "next-intl/server";


export default async function HomePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("common");

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col items-start justify-center gap-6 px-6">
      <h1 className="text-4xl font-semibold">{t("brand")}</h1>
      <p className="text-lg text-[--color-muted]">{t("tagline")}</p>
      <Button>{t("actions.buy")}</Button>
    </main>
  );
}
