// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GTM_ID, GoogleTagManager } from "./GoogleTagManager";

import { scrubScript } from "@/lib/scrubUrl";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("GoogleTagManager", () => {
  it("renders nothing outside production", () => {
    vi.stubEnv("NODE_ENV", "test");
    const { container } = render(<GoogleTagManager />);
    expect(container.innerHTML).toBe("");
  });

  it("loads the container and scrubs the same params Metrika does", () => {
    vi.stubEnv("NODE_ENV", "production");
    const { container } = render(<GoogleTagManager />);
    const script = container.querySelector("script")?.innerHTML ?? "";

    expect(script).toContain(`gtm.js?id=`);
    expect(script).toContain(JSON.stringify(GTM_ID));
    // The scrubbed page_location is pushed before the loader runs, from the
    // single list in lib/scrubUrl — a hand-kept copy is how Metrika leaked a
    // token once (threat-model.md).
    expect(script).toContain(scrubScript("_gtU"));
    expect(container.querySelector("noscript")).not.toBeNull();
  });
});
