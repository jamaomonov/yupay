/** Skeleton of the item page while it streams in. */
export default function Loading() {
  return (
    <main className="mx-auto min-h-screen max-w-[1320px] px-4 pb-28 pt-[104px] sm:px-6">
      <div className="bg-muted mb-4 h-4 w-40 animate-pulse rounded" />
      <section className="border-border bg-card grid gap-6 rounded-2xl border p-5 md:grid-cols-2 md:p-8">
        <div className="bg-muted aspect-[4/3] animate-pulse rounded-xl" />
        <div className="flex flex-col gap-3">
          <div className="bg-muted h-4 w-24 animate-pulse rounded" />
          <div className="bg-muted h-8 w-3/4 animate-pulse rounded-lg" />
          <div className="bg-muted mt-4 h-24 animate-pulse rounded-xl" />
        </div>
      </section>
    </main>
  );
}
