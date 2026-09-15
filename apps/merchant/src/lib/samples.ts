/**
 * Signed request samples, per endpoint, in the three languages an integrator
 * actually reaches for.
 *
 * Generated rather than written, for the reason the example bodies are: a
 * hand-written sample is a second copy of the canonical string, and the day
 * somebody adds a field to it the samples are where the drift hides.
 *
 * **There is no "try it" button on this reference, and there will not be
 * one.** Sending a signed request needs the merchant's secret, and that
 * credential belongs on their server — putting a box on a web page that asks
 * for it would undo the one rule the whole auth design rests on. Running an
 * order from a docs page would also spend real money on a real supplier. The
 * sample is the thing you paste into your own terminal, where your secret
 * already lives.
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

function curl({ method, path, query, body, baseUrl }: SampleInput): string {
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

function python({ method, path, query, body, baseUrl }: SampleInput): string {
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

function node({ method, path, query, body, baseUrl }: SampleInput): string {
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

/** The canonical string for this request, shown beside the samples. */
export function canonicalString(input: SampleInput): string {
  return canonical(input.method, input.path, input.query, input.body !== null);
}
