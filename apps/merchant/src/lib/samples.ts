/**
 * Request samples, per endpoint, in the three languages an integrator
 * actually reaches for.
 *
 * `sampleFor` is the default everywhere: one `Authorization: Bearer ypk_…`
 * header (ADR-0103). `signedSampleFor` is the original HMAC-signed request,
 * still accepted for keys issued before the single key, and shown only on the
 * authentication page.
 *
 * Generated rather than written, for the reason the example bodies are: a
 * hand-written sample is a second copy of the contract, and the day somebody
 * adds a field to it the samples are where the drift hides.
 *
 * **There is no "try it" button on this reference.** The key belongs on the
 * merchant's server, and running an order from a docs page would spend real
 * money on a real supplier.
 */

export type Language = "curl" | "python" | "node";

export const LANGUAGES: { id: Language; label: string }[] = [
  { id: "curl", label: "cURL" },
  { id: "python", label: "Python" },
  { id: "node", label: "Node.js" },
];

export interface SampleInput {
  method: string;
  /** The path with its parameters already filled in, e.g. `/merchant/v1/orders/shop-10482`. */
  path: string;
  query: string;
  /** The request body as JSON, or `null` for a request that has none. */
  body: string | null;
  baseUrl: string;
}

function canonical(method: string, path: string, query: string, hasBody: boolean): string {
  const digest = hasBody ? "sha256_hex(body)" : "sha256_hex('')";
  // Real newlines: the string genuinely contains them, and five lines is what
  // makes "the empty query still takes its place" visible at a glance —
  // rendered as one line with literal \n it is a wall nobody counts.
  return ["{timestamp}", method, path, query, digest].join("\n");
}

function signedCurl({ method, path, query, body, baseUrl }: SampleInput): string {
  const url = `${baseUrl}${path}${query === "" ? "" : `?${query}`}`;
  const bodyFile =
    body === null ? "" : `\nBODY='${body.replaceAll("\n", "").replaceAll(/\s+/g, " ")}'`;
  const digest =
    body === null
      ? `DIGEST=$(printf '' | openssl dgst -sha256 -hex | awk '{print $2}')`
      : `DIGEST=$(printf '%s' "$BODY" | openssl dgst -sha256 -hex | awk '{print $2}')`;
  const send =
    body === null
      ? `curl -sS -X ${method} "${url}" \\\n  -H "X-Merchant-Key: $KEY_ID" \\\n  -H "X-Merchant-Timestamp: $TS" \\\n  -H "X-Merchant-Signature: $SIG"`
      : `curl -sS -X ${method} "${url}" \\\n  -H "X-Merchant-Key: $KEY_ID" \\\n  -H "X-Merchant-Timestamp: $TS" \\\n  -H "X-Merchant-Signature: $SIG" \\\n  -H "Content-Type: application/json" \\\n  -d "$BODY"`;
  return `KEY_ID='ypm_your_key_id'
SECRET='ypms_your_secret'
TS=$(date +%s)${bodyFile}

${digest}
CANONICAL="$TS
${method}
${path}
${query}
$DIGEST"
SIG=$(printf '%s' "$CANONICAL" | openssl dgst -sha256 -hmac "$SECRET" -hex | awk '{print $2}')

${send}`;
}

function signedPython({ method, path, query, body, baseUrl }: SampleInput): string {
  const payload =
    body === null
      ? 'body = b""'
      : `body = json.dumps(${body.replaceAll("\n", "\n")}, separators=(",", ":")).encode()`;
  const send =
    body === null
      ? `resp = httpx.request("${method}", BASE + PATH, params=QUERY or None, headers=headers)`
      : `headers["Content-Type"] = "application/json"\nresp = httpx.request("${method}", BASE + PATH, params=QUERY or None, content=body, headers=headers)`;
  return `import hashlib, hmac, json, time
import httpx

BASE = "${baseUrl}"
PATH = "${path}"
QUERY = "${query}"
KEY_ID = "ypm_your_key_id"
SECRET = "ypms_your_secret"

${payload}
timestamp = str(int(time.time()))
canonical = "\\n".join([
    timestamp,
    "${method}",
    PATH,
    QUERY,
    hashlib.sha256(body).hexdigest(),
])
signature = hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()

headers = {
    "X-Merchant-Key": KEY_ID,
    "X-Merchant-Timestamp": timestamp,
    "X-Merchant-Signature": signature,
}
${send}
resp.raise_for_status()
print(resp.json())`;
}

function signedNode({ method, path, query, body, baseUrl }: SampleInput): string {
  const payload =
    body === null
      ? 'const body = "";'
      : `const body = JSON.stringify(${body.replaceAll("\n", "\n")});`;
  const send =
    body === null
      ? `const response = await fetch(url, { method: "${method}", headers });`
      : `headers["Content-Type"] = "application/json";\nconst response = await fetch(url, { method: "${method}", headers, body });`;
  return `import { createHash, createHmac } from "node:crypto";

const BASE = "${baseUrl}";
const PATH = "${path}";
const QUERY = "${query}";
const KEY_ID = "ypm_your_key_id";
const SECRET = "ypms_your_secret";

${payload}
const timestamp = String(Math.floor(Date.now() / 1000));
const digest = createHash("sha256").update(body).digest("hex");
const canonical = [timestamp, "${method}", PATH, QUERY, digest].join("\\n");
const signature = createHmac("sha256", SECRET).update(canonical).digest("hex");

const url = BASE + PATH + (QUERY ? "?" + QUERY : "");
const headers = {
  "X-Merchant-Key": KEY_ID,
  "X-Merchant-Timestamp": timestamp,
  "X-Merchant-Signature": signature,
};
${send}
if (!response.ok) throw new Error(await response.text());
console.log(await response.json());`;
}

function oneLine(body: string): string {
  return body.replaceAll("\n", "").replaceAll(/\s+/g, " ");
}

function curl({ method, path, query, body, baseUrl }: SampleInput): string {
  const url = `${baseUrl}${path}${query === "" ? "" : `?${query}`}`;
  const auth = `curl -sS -X ${method} "${url}" \\\n  -H "Authorization: Bearer $API_KEY"`;
  return body === null
    ? `API_KEY='ypk_your_api_key'\n\n${auth}`
    : `API_KEY='ypk_your_api_key'\n\n${auth} \\\n  -H "Content-Type: application/json" \\\n  -d '${oneLine(body)}'`;
}

function python({ method, path, query, body, baseUrl }: SampleInput): string {
  const send =
    body === null
      ? `resp = httpx.request("${method}", BASE + PATH, params=QUERY or None, headers=headers)`
      : `resp = httpx.request("${method}", BASE + PATH, params=QUERY or None, json=${body}, headers=headers)`;
  return `import httpx

BASE = "${baseUrl}"
PATH = "${path}"
QUERY = "${query}"
API_KEY = "ypk_your_api_key"

headers = {"Authorization": f"Bearer {API_KEY}"}
${send}
resp.raise_for_status()
print(resp.json())`;
}

function node({ method, path, query, body, baseUrl }: SampleInput): string {
  const send =
    body === null
      ? `const response = await fetch(url, { method: "${method}", headers });`
      : `headers["Content-Type"] = "application/json";\nconst response = await fetch(url, {\n  method: "${method}",\n  headers,\n  body: JSON.stringify(${body}),\n});`;
  return `const BASE = "${baseUrl}";
const PATH = "${path}";
const QUERY = "${query}";
const API_KEY = "ypk_your_api_key";

const url = BASE + PATH + (QUERY ? "?" + QUERY : "");
const headers = { Authorization: \`Bearer \${API_KEY}\` };
${send}
if (!response.ok) throw new Error(await response.text());
console.log(await response.json());`;
}

/** The default sample: the single API key as a bearer token (ADR-0103). */
export function sampleFor(language: Language, input: SampleInput): string {
  switch (language) {
    case "curl":
      return curl(input);
    case "python":
      return python(input);
    case "node":
      return node(input);
  }
}

/** The original HMAC-signed request, for keys issued before the single key. */
export function signedSampleFor(language: Language, input: SampleInput): string {
  switch (language) {
    case "curl":
      return signedCurl(input);
    case "python":
      return signedPython(input);
    case "node":
      return signedNode(input);
  }
}

/** The canonical string for this request, shown beside the samples. */
export function canonicalString(input: SampleInput): string {
  return canonical(input.method, input.path, input.query, input.body !== null);
}
