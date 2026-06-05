"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import { apiFetch } from "@/lib/client";

function VerifyInner() {
  const token = useSearchParams().get("token");
  const [state, setState] = useState<"pending" | "ok" | "error">(token ? "pending" : "error");
  const fired = useRef(false);

  useEffect(() => {
    if (fired.current || !token) return;
    fired.current = true;
    apiFetch("/auth/verify-email", {
      method: "POST",
      anonymous: true,
      body: { token },
    })
      .then(() => {
        setState("ok");
      })
      .catch(() => {
        setState("error");
      });
  }, [token]);

  return (
    <main className="mx-auto max-w-[420px] px-4 py-16 text-center">
      {state === "pending" && <p>Подтверждаем…</p>}
      {state === "ok" && <p>Email подтверждён ✓</p>}
      {state === "error" && <p>Ссылка недействительна или устарела.</p>}
    </main>
  );
}

export default function VerifyPage() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-[420px] px-4 py-16 text-center">
          <p>Подтверждаем…</p>
        </main>
      }
    >
      <VerifyInner />
    </Suspense>
  );
}
