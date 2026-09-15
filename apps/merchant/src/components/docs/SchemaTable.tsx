import Link from "next/link";

import type { SchemaNode } from "@/lib/contract";

import { Prose } from "@/components/docs/Prose";
import { isNullable, refName, resolve, typeLabel } from "@/lib/contract";
import { pathFor } from "@/lib/locale-href";

/**
 * A schema's fields, as rows a developer scans.
 *
 * Nested objects expand **one** level and then link to their own page. Fully
 * inlining the tree puts the same model on six pages and makes each of them
 * scroll for a minute; never expanding makes a reader click three times to
 * learn the shape of a response. One level is where the two stop hurting.
 */
export function SchemaTable({
  node,
  locale,
  required,
  depth = 0,
}: {
  node: SchemaNode | undefined;
  locale: string;
  /** Names the parent declared required, since JSON Schema keeps that above. */
  required?: string[];
  depth?: number;
}) {
  if (node === undefined) return null;
  const target = node.$ref === undefined ? node : resolve(node);
  const fields = target.type === "array" ? resolve(target.items ?? {}) : target;
  const properties = fields.properties;

  if (properties === undefined) {
    return (
      <p className="text-tx-mute font-mono text-[13px]">
        {typeLabel(node)}
        {target.description !== undefined && (
          <span className="text-tx-dim font-sans"> — {target.description}</span>
        )}
      </p>
    );
  }

  const mandatory = new Set(required ?? fields.required ?? []);

  return (
    <dl className="divide-border divide-y">
      {Object.entries(properties).map(([name, child]) => {
        const model = refName(child) ?? refName(child.items ?? {});
        const nested =
          depth === 0 && model === null
            ? (resolve(child).properties ?? child.items?.properties)
            : undefined;
        return (
          <div key={name} className="py-3.5">
            {/* The flex row IS the <dt>. It used to be a second <div> with the
                <dt> inside it, which puts the term two levels below the <dl>
                and breaks the pairing — HTML5 allows exactly one grouping
                <div>, not two. */}
            <dt className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
              <span className="font-mono text-[13px] font-semibold">{name}</span>
              <span className="text-tx-dim font-mono text-[12px]">
                {model === null ? (
                  typeLabel(child)
                ) : (
                  <Link
                    href={pathFor(locale, `/docs/schemas/${model}`)}
                    className="underline-offset-4 hover:underline"
                  >
                    {typeLabel(child)}
                  </Link>
                )}
              </span>
              {mandatory.has(name) ? (
                <span className="text-danger text-[11px] font-semibold">required</span>
              ) : (
                isNullable(child) && <span className="text-tx-dim text-[11px]">nullable</span>
              )}
            </dt>
            {child.description !== undefined && (
              <dd className="text-tx-mute mt-1.5 text-[13px]">
                <Prose text={child.description} lang="en" />
              </dd>
            )}
            <Constraints node={child} />
            {nested !== undefined && (
              <dd className="border-border mt-3 border-l pl-4">
                <SchemaTable node={child} locale={locale} depth={depth + 1} />
              </dd>
            )}
          </div>
        );
      })}
    </dl>
  );
}

/** The bounds a caller has to respect, when the schema states any. */
function Constraints({ node }: { node: SchemaNode }) {
  const inner = node.anyOf?.find((branch) => branch.type !== "null") ?? node;
  const bits: string[] = [];
  if (inner.enum !== undefined) bits.push(`one of ${inner.enum.map(String).join(", ")}`);
  if (inner.minimum !== undefined) bits.push(`min ${String(inner.minimum)}`);
  if (inner.exclusiveMinimum !== undefined) bits.push(`> ${String(inner.exclusiveMinimum)}`);
  if (inner.maximum !== undefined) bits.push(`max ${String(inner.maximum)}`);
  if (inner.minLength !== undefined) bits.push(`≥ ${String(inner.minLength)} chars`);
  if (inner.maxLength !== undefined) bits.push(`≤ ${String(inner.maxLength)} chars`);
  if (inner.pattern !== undefined) bits.push(`matches ${inner.pattern}`);
  if (bits.length === 0) return null;
  return <dd className="text-tx-dim mt-1.5 font-mono text-[11.5px]">{bits.join(" · ")}</dd>;
}
