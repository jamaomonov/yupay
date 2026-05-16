/** Wraps protected routes: redirect to /login if not logged in, 403 page if not admin. */

import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuthStore } from "./authStore";
import { useMe } from "./useMe";

export function AuthGuard() {
  const token = useAuthStore((s) => s.token);
  const location = useLocation();
  const meQuery = useMe(!!token);

  if (!token) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }

  if (meQuery.isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-[--color-muted]">
        Загрузка…
      </div>
    );
  }

  if (meQuery.isError) {
    // /auth/me failed — treat as logged out.
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }

  if (!meQuery.data?.roles.includes("admin")) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-6">
        <h1 className="text-3xl font-semibold">403</h1>
        <p className="text-[--color-muted]">У этого аккаунта нет роли admin.</p>
        <p className="text-sm text-[--color-muted]">
          Попроси оператора выполнить <code>grant_admin --tg-id …</code>.
        </p>
      </main>
    );
  }

  return <Outlet />;
}
