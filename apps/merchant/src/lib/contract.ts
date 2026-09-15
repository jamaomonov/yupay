import { readFileSync } from "node:fs";
import path from "node:path";

/**
 * The published `/merchant/v1` contract, read from the repo at build time.
 *
 * From a **file**, not from the live API. A Next build prerenders against
 * whatever API it can reach, which during a deploy is the one being replaced —
 * a docs page that fetched its own schema would document the version it is
 * about to supersede. `make gen-api` writes this file and CI fails on drift,
 * so the page and the API move together or neither does.
 *
 * Server-only: `node:fs` never reaches a client bundle, and every page that
 * reads this is a Server Component.
 */

const CONTRACT = path.join(process.cwd(), "..", "..", "docs", "api", "merchant-openapi.json");

/**
 * The host every sample on this site tells an integrator to call.
 *
 * The contract's own `servers[0]` is **not** trusted for this. It is written
 * by `make gen-api` on whoever's machine ran it, and it shipped saying
 * `http://localhost:8000` under the label "Production" — so every cURL block
 * in the published reference pointed at the reader's own laptop. The exporter
 * now pins the value, and this prefers the build's own env on top of that, so
 * the samples are right even if the file is wrong again.
 *
 * `NEXT_PUBLIC_API_BASE_URL` is what the image is built with (see the
 * `merchant` row in `.github/workflows/build.yml`) and what every request
 * from this app already goes to — the samples and the cabinet cannot disagree.
 */
export function apiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (configured !== undefined && configured !== "") return configured.replace(/\/$/, "");
  const declared = contract().servers?.[0]?.url;
  return declared === undefined ? "https://api.yupay.uz" : declared.replace(/\/$/, "");
}

/** A JSON Schema node, as far as the reference renders one. */
export interface SchemaNode {
  $ref?: string;
  type?: string | string[];
  format?: string;
  title?: string;
  description?: string;
  enum?: (string | number)[];
  const?: string | number;
  default?: unknown;
  items?: SchemaNode;
  properties?: Record<string, SchemaNode>;
  required?: string[];
  anyOf?: SchemaNode[];
  allOf?: SchemaNode[];
  oneOf?: SchemaNode[];
  additionalProperties?: boolean | SchemaNode;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  examples?: unknown[];
}

export interface Parameter {
  name: string;
  in: "path" | "query" | "header" | "cookie";
  required?: boolean;
  description?: string;
  schema?: SchemaNode;
}

export interface Operation {
  operationId: string;
  summary?: string;
  description?: string;
  tags?: string[];
  parameters?: Parameter[];
  requestBody?: { required?: boolean; content?: Record<string, { schema?: SchemaNode }> };
  responses: Record<
    string,
    { description?: string; content?: Record<string, { schema?: SchemaNode }> }
  >;
  security?: Record<string, string[]>[];
}

export interface Contract {
  openapi: string;
  info: {
    title: string;
    version: string;
    description?: string;
    contact?: { name?: string; url?: string };
  };
  servers?: { url: string; description?: string }[];
  tags?: { name: string; description?: string }[];
  paths: Record<string, Record<string, Operation>>;
  components: {
    schemas: Record<string, SchemaNode>;
    securitySchemes?: Record<
      string,
      { type: string; in?: string; name?: string; description?: string }
    >;
  };
}

let cached: Contract | null = null;

export function contract(): Contract {
  // Read once per process. The file cannot change while a build runs, and a
  // page per operation would otherwise parse 70 KB of JSON once each.
  cached ??= JSON.parse(readFileSync(CONTRACT, "utf-8")) as Contract;
  return cached;
}

/** One operation, flattened with the things a page needs beside it. */
export interface Endpoint {
  id: string;
  method: string;
  path: string;
  tag: string;
  operation: Operation;
}

/** Every documented operation, in the order the contract lists them. */
export function endpoints(): Endpoint[] {
  const out: Endpoint[] = [];
  for (const [urlPath, item] of Object.entries(contract().paths)) {
    for (const [method, operation] of Object.entries(item)) {
      out.push({
        id: slugOf(method, urlPath),
        method: method.toUpperCase(),
        path: urlPath,
        tag: operation.tags?.[0] ?? "API",
        operation,
      });
    }
  }
  return out;
}

/**
 * The URL segment for an operation.
 *
 * Derived from the method and path rather than from `operationId`, so a
 * rename in the contract's client-facing names does not break every link
 * somebody bookmarked. `post-orders`, `get-orders-merchant-order-id`.
 */
export function slugOf(method: string, urlPath: string): string {
  const parts = urlPath
    .replace("/merchant/v1", "")
    .split("/")
    .filter(Boolean)
    .map((part) => part.replaceAll(/[{}]/g, "").replaceAll("_", "-"));
  return [method.toLowerCase(), ...parts].join("-");
}

/** Resolve a `$ref`, or return the node unchanged. */
export function resolve(node: SchemaNode): SchemaNode {
  if (node.$ref === undefined) return node;
  const name = node.$ref.replace("#/components/schemas/", "");
  return contract().components.schemas[name] ?? {};
}

/** The model name a `$ref` points at, for linking to its own page. */
export function refName(node: SchemaNode | undefined): string | null {
  if (node?.$ref === undefined) return null;
  return node.$ref.replace("#/components/schemas/", "");
}

/**
 * A human type label: `string`, `string · date-time`, `MerchantSkuOut`,
 * `array<MerchantBrandOut>`, `"fixed" | "unit" | "amount"`.
 *
 * Built from the node rather than from a lookup table because the contract
 * expresses the same thing several ways — a nullable field is `anyOf` with a
 * `null` branch, an enum is `enum`, a constant is `const`.
 */
export function typeLabel(node: SchemaNode | undefined): string {
  if (node === undefined) return "any";
  const named = refName(node);
  if (named !== null) return named;
  if (node.enum !== undefined) {
    return node.enum.map((value) => JSON.stringify(value)).join(" | ");
  }
  if (node.const !== undefined) return JSON.stringify(node.const);
  if (node.anyOf !== undefined) {
    // `T | null` is how every optional field arrives; render it as the type
    // plus a nullable mark rather than as a two-branch union nobody reads.
    const branches = node.anyOf.filter((branch) => branch.type !== "null");
    const label = branches.map(typeLabel).join(" | ");
    return branches.length < node.anyOf.length ? `${label} | null` : label;
  }
  if (node.allOf?.length === 1 && node.allOf[0] !== undefined) return typeLabel(node.allOf[0]);
  if (node.type === "array") return `array<${typeLabel(node.items)}>`;
  const base = Array.isArray(node.type) ? node.type.join(" | ") : (node.type ?? "object");
  return node.format === undefined ? base : `${base} · ${node.format}`;
}

/** `true` when the node is `T | null` — the shape every optional field takes. */
export function isNullable(node: SchemaNode | undefined): boolean {
  return node?.anyOf?.some((branch) => branch.type === "null") ?? false;
}

/** The body schema of a request or a response, for the one content type we use. */
export function bodySchema(
  content: Record<string, { schema?: SchemaNode }> | undefined,
): SchemaNode | undefined {
  return content?.["application/json"]?.schema;
}
