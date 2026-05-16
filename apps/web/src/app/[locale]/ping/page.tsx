/**
 * Smoke route — fetches the catalog ping endpoint from the API to prove the wiring
 * end-to-end. Will be deleted once real catalog routes land.
 */

export const dynamic = "force-dynamic";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default async function PingPage() {
  let body: { module?: string; status?: string; error?: string };
  try {
    const res = await fetch(`${apiBase}/api/v1/catalog/ping`, { cache: "no-store" });
    body = (await res.json()) as { module?: string; status?: string };
  } catch (error) {
    body = { error: error instanceof Error ? error.message : "unknown" };
  }
  return (
    <main className="mx-auto max-w-2xl p-8">
      <h1 className="text-2xl font-semibold">YuPay API ping</h1>
      <pre className="mt-4 rounded-md bg-[--color-subtle] p-4 text-sm">
        {JSON.stringify(body, null, 2)}
      </pre>
    </main>
  );
}
