"use client";

import { useRouter } from "next/navigation";
import { use } from "react";

import { AuthForm } from "@/components/auth/AuthForm";
import { useAuth } from "@/lib/auth";

export default function RegisterPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = use(params);
  const { register } = useAuth();
  const router = useRouter();
  return (
    <main className="mx-auto max-w-[420px] px-4 py-16">
      <h1 className="font-display mb-6 text-2xl font-bold tracking-[-0.02em]">Регистрация</h1>
      <AuthForm
        mode="register"
        locale={locale}
        onSubmit={async (v) => {
          await register(v.email, v.password, locale);
          router.push(`/${locale}/account`);
        }}
      />
    </main>
  );
}
