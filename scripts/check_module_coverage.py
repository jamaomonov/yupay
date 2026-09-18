"""Per-module coverage ratchet (AGENTS.md §8).

Reads a ``coverage json`` report and fails if any tracked module drops below
its floor. Floors are the *current* levels (minus a small flake margin), not
the targets — they only prevent regression. Raise a floor every time tests
push a module above it; the ratchet ends when every critical module holds
the 95% target (payments, wallet, fulfillment, supplier adapters) and the
default gate reaches 80%.

Usage: python scripts/check_module_coverage.py coverage.json
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict

# module prefix (after apps/api/src/yupay/) -> (floor %, target %)
FLOORS: dict[str, tuple[float, float]] = {
    "modules/payments": (96.0, 95.0),
    "modules/wallet": (94.0, 95.0),
    "modules/fulfillment": (95.0, 95.0),
    "modules/inventory": (89.0, 95.0),
    "modules/integrations": (90.0, 95.0),
    # Not on AGENTS.md §8's named list, but route-deciding and money-adjacent
    # (a wrong route picks the wrong cost basis — ADR-0083) the same way
    # inventory and integrations are, and this branch alone added ~400 LOC
    # here. Floor set from the sourcing/bulk-rules/brand-overview integration
    # suites alone (96.02% measured 2026-09-18), a small margin under.
    "modules/sourcing": (95.0, 95.0),
}


def main(path: str) -> int:
    cov = json.load(open(path))
    sums: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for file_path, data in cov["files"].items():
        for prefix in FLOORS:
            if f"/{prefix}/" in file_path or file_path.startswith(prefix):
                s = data["summary"]
                sums[prefix][0] += s["covered_lines"] + s.get("covered_branches", 0)
                sums[prefix][1] += s["num_statements"] + s.get("num_branches", 0)

    failed = False
    for prefix, (floor, target) in sorted(FLOORS.items()):
        covered, total = sums.get(prefix, [0.0, 0.0])
        if total == 0:
            print(f"ERROR: no coverage data for {prefix}")
            failed = True
            continue
        pct = 100.0 * covered / total
        status = "ok" if pct >= floor else "FAIL"
        print(f"{status:4s} {prefix:28s} {pct:5.1f}%  (floor {floor:.0f}%, target {target:.0f}%)")
        if pct < floor:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "coverage.json"))
