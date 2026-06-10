import { describe, expect, it } from "vitest";

import { serializeJsonLd } from "./json-ld";

describe("serializeJsonLd", () => {
  it("escapes </script> so API-sourced strings cannot break out of the tag", () => {
    const out = serializeJsonLd({ name: 'Evil</script><script>alert("xss")</script>' });
    expect(out).not.toContain("</script>");
    expect(out).not.toContain("<");
  });

  it("round-trips back to the original object", () => {
    const data = { name: "Steam <Wallet> & Co", faq: ["a</script>b", "c<!--d"] };
    expect(JSON.parse(serializeJsonLd(data))) // < is valid JSON
      .toEqual(data);
  });

  it("leaves plain payloads untouched", () => {
    expect(serializeJsonLd({ "@type": "Brand", name: "Netflix" })).toBe(
      '{"@type":"Brand","name":"Netflix"}',
    );
  });
});
