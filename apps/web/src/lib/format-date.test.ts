import { describe, expect, it } from "vitest";

import { formatDate } from "./format-date";

// Local-time constructor: the helper formats in the runtime's zone, like Intl.
const AT = new Date(2026, 10, 13, 9, 5);

describe("formatDate", () => {
  it("spells Uzbek out instead of Chrome's «2026 M11 13»", () => {
    expect(formatDate("uz", AT, "date")).toBe("13-noy, 2026");
    expect(formatDate("uz", AT, "dateTime")).toBe("13-noy, 2026, 09:05");
    expect(formatDate("uz", AT, "dayMonth")).toBe("13-noyabr");
    expect(formatDate("uz", AT, "numeric")).toBe("13.11.2026");
    expect(formatDate("uz", AT, "time")).toBe("09:05");
  });

  it("keeps Intl for Russian and English", () => {
    expect(formatDate("ru", AT, "numeric")).toBe("13.11.2026");
    expect(formatDate("en", AT, "dayMonth")).toBe("November 13");
  });
});
