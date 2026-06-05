"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect } from "react";

import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";

export default function AccountPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = use(params);
  const { user, isLoading, logout } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !user) {
      router.push(`/${locale}/login`);
    }
  }, [isLoading, user, router, locale]);

  if (isLoading) {
    return (
      <main className="mx-auto max-w-[560px] px-4 py-16">
        <p className="text-tx-dim text-sm">Загрузка…</p>
      </main>
    );
  }

  if (!user) {
    return null;
  }

  function handleLogout() {
    logout();
    router.push(`/${locale}`);
  }

  return (
    <main className="mx-auto max-w-[560px] px-4 py-16">
      <h1 className="font-display mb-6 text-2xl font-bold tracking-[-0.02em]">Аккаунт</h1>

      <div className="border-border bg-card rounded-2xl border p-6">
        <div className="mb-4 space-y-1">
          <p className="text-foreground font-semibold">
            {user.display_name ?? user.email ?? "Пользователь"}
          </p>
          {user.email && <p className="text-tx-dim text-sm">{user.email}</p>}
        </div>

        <dl className="mb-6 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <dt className="text-tx-dim">Язык</dt>
          <dd className="text-foreground">{user.locale}</dd>

          <dt className="text-tx-dim">Валюта</dt>
          <dd className="text-foreground">{user.display_currency}</dd>
        </dl>

        <div className="flex flex-wrap gap-3">
          <Link
            href={`/${locale}/account/orders`}
            className={buttonStyles({ variant: "ghost", size: "sm" })}
          >
            Мои заказы
          </Link>
          <button
            type="button"
            onClick={handleLogout}
            className={buttonStyles({ variant: "ghost", size: "sm" })}
          >
            Выйти
          </button>
        </div>
      </div>
    </main>
  );
}
