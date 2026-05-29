import { AlertCircle } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { useT } from "@/lib/i18n";

export default function NotFound() {
  const { t } = useT();
  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-gray-50">
      <Card className="mx-4 w-full max-w-md">
        <CardContent className="pt-6">
          <div className="mb-4 flex gap-2">
            <AlertCircle className="h-8 w-8 text-red-500" />
            <h1 className="text-2xl font-bold text-gray-900">{t("app.notFound")}</h1>
          </div>

          <p className="mt-4 text-sm text-gray-600">{t("app.notFoundBody")}</p>
        </CardContent>
      </Card>
    </div>
  );
}
