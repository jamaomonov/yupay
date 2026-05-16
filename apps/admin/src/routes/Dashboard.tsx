import { useAuthStore } from "@/features/auth/authStore";

export function DashboardPage() {
  const me = useAuthStore((s) => s.me);
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Привет, {me?.display_name ?? "админ"} 👋</h1>
        <p className="mt-1 text-sm text-[--color-muted]">
          Здесь будут метрики: заказы за день, выручка, проваленные платежи, остатки кодов.
        </p>
      </header>
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {["Заказы (24ч)", "Выручка (24ч)", "Stock", "Refunds"].map((label) => (
          <article
            key={label}
            className="rounded-lg border bg-[--color-bg] p-4"
          >
            <p className="text-sm text-[--color-muted]">{label}</p>
            <p className="mt-2 text-2xl font-semibold">—</p>
          </article>
        ))}
      </section>
    </div>
  );
}
