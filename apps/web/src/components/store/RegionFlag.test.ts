import { readdirSync } from "node:fs";
import { join } from "node:path";

import { FLAG_CODES } from "@yupay/utils";
import { expect, it } from "vitest";

// `FLAG_CODES` is what the code may link to; the files are what is served.
// A code without a file is a broken image on a region chip, a file without a
// code is dead weight — both apps ship the same set.
const ROOT = join(__dirname, "../../../..");

it.each(["web", "miniapp"])("%s ships exactly the flags the code links to", (app) => {
  const files = readdirSync(join(ROOT, app, "public/flags/region"))
    .filter((f) => f.endsWith(".svg"))
    .map((f) => f.replace(/\.svg$/, ""))
    .sort();
  expect(files).toEqual([...FLAG_CODES].sort());
});
