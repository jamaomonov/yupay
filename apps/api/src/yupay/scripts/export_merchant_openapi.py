"""Export the published `/merchant/v1` contract to a JSON file.

The narrowed document `GET /merchant/openapi.json` serves — six paths and the
models they reach — written to the repo so the cabinet's documentation page
builds from a file rather than from a live API.

That matters twice. A Next.js build prerenders against whatever API it can
reach, which during a deploy is the *previous* one, so a docs page fetching
its own schema would render the schema it is replacing. And CI can diff this
file to catch a contract change nobody meant to publish.

Usage:
    python -m yupay.scripts.export_merchant_openapi /path/to/merchant-openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from yupay.bootstrap import create_app
from yupay.modules.merchants.machine_openapi import PUBLISHED_BASE_URL, build

_EXPECTED_ARGV = 2  # script name + output path


def main(argv: list[str]) -> int:
    """Write the merchant contract to the file at ``argv[1]``."""
    if len(argv) != _EXPECTED_ARGV:
        print(
            "Usage: python -m yupay.scripts.export_merchant_openapi <output.json>",
            file=sys.stderr,
        )
        return 2

    output = Path(argv[1]).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    document = build(create_app().openapi(), base_url=PUBLISHED_BASE_URL)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
