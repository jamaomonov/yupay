import { Button } from "@yupay/ui";
import { Compass } from "lucide-react";
import { Link } from "react-router-dom";

import { EmptyState } from "@/components/States";

/**
 * Catch-all for unknown paths. Previously the wildcard route silently
 * redirected to the dashboard, which made typos/dead links indistinguishable
 * from "you're already home" — this renders an explicit 404 instead.
 */
export function NotFoundPage() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <EmptyState
        icon={Compass}
        title="Страница не найдена"
        description="Такого адреса нет в админке — проверь ссылку или вернись на дашборд."
        action={
          <Link to="/">
            <Button type="button">На дашборд</Button>
          </Link>
        }
      />
    </div>
  );
}
