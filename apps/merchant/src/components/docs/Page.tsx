import type { ReactNode } from "react";

/** The one column a guide page sits in, so five of them cannot drift apart. */
export function DocsPage({
  eyebrow,
  title,
  lead,
  children,
}: {
  eyebrow?: string;
  title: string;
  lead?: string;
  children: ReactNode;
}) {
  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-8 sm:py-10">
      {eyebrow !== undefined && (
        <p className="text-tx-dim text-[11px] font-semibold tracking-[0.09em]">{eyebrow}</p>
      )}
      <h1 className="font-display mt-1.5 text-2xl font-semibold tracking-tight sm:text-3xl">
        {title}
      </h1>
      {lead !== undefined && (
        <p className="text-tx-mute mt-4 text-[15px] leading-relaxed">{lead}</p>
      )}
      <div className="mt-9 space-y-10">{children}</div>
    </div>
  );
}

/** A titled block, with the anchor a deep link needs. */
export function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section>
      <h2 id={id} className="border-border scroll-mt-6 border-b pb-2 text-lg font-semibold">
        {title}
      </h2>
      <div className="mt-4 space-y-4">{children}</div>
    </section>
  );
}

/** A three-column reference table — headers, statuses, codes. */
export function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <div className="border-border overflow-x-auto rounded-xl border">
      <table className="w-full min-w-[34rem] text-left text-[13px]">
        <thead className="border-border bg-card-2 text-tx-dim border-b">
          <tr>
            {head.map((cell) => (
              <th key={cell} className="px-4 py-2.5 font-semibold">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} className="border-border border-b last:border-0">
              {row.map((cell, column) => (
                <td key={column} className="px-4 py-3 align-top">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Inline code, the same shape `Prose` renders. */
export function Code({ children }: { children: ReactNode }) {
  return (
    <code className="bg-card-2 text-foreground rounded px-1 py-0.5 font-mono text-[0.9em]">
      {children}
    </code>
  );
}
