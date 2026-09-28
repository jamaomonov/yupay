/** Skeleton grid while the catalogue page streams in. */
export default function Loading() {
  return (
    <main className="mx-auto min-h-screen max-w-[1320px] px-4 pb-28 pt-[104px] sm:px-6">
      <div className="bg-muted mb-4 h-8 w-64 animate-pulse rounded-lg" />
      <ul className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
        {Array.from({ length: 10 }, (_, i) => (
          <li key={i} className="bg-muted aspect-[3/4] animate-pulse rounded-xl" />
        ))}
      </ul>
    </main>
  );
}
