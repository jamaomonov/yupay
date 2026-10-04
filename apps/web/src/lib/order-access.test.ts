// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";

import { getOrderAccess, saveOrderAccess } from "./order-access";

beforeEach(() => {
  window.localStorage.clear();
});

describe("order access store", () => {
  it("returns what was saved for that order only", () => {
    saveOrderAccess("o1", "t1");
    expect(getOrderAccess("o1")).toBe("t1");
    expect(getOrderAccess("o2")).toBeNull();
  });

  it("replaces a token for the same order", () => {
    saveOrderAccess("o1", "old");
    saveOrderAccess("o1", "new");
    expect(getOrderAccess("o1")).toBe("new");
  });

  it("keeps the newest fifty", () => {
    for (let i = 0; i < 55; i += 1) saveOrderAccess(`o${String(i)}`, `t${String(i)}`);
    expect(getOrderAccess("o54")).toBe("t54");
    expect(getOrderAccess("o0")).toBeNull();
  });

  it("survives garbage in storage", () => {
    window.localStorage.setItem("yupay.web.order_access", "[1,2]");
    expect(getOrderAccess("o1")).toBeNull();
    saveOrderAccess("o1", "t1");
    expect(getOrderAccess("o1")).toBe("t1");
  });
});
