"""Export the OpenAPI schema of the running app to a JSON file.

Used by CI / ``make gen-api`` to keep ``docs/api/openapi.json`` in sync with the FastAPI app.

Usage:
    python -m yupay.scripts.export_openapi /path/to/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from yupay.bootstrap import create_app

_EXPECTED_ARGV = 2  # script name + output path


def main(argv: list[str]) -> int:
    """Write the OpenAPI schema to the file at ``argv[1]``."""
    if len(argv) != _EXPECTED_ARGV:
        print("Usage: python -m yupay.scripts.export_openapi <output.json>", file=sys.stderr)
        return 2

    output = Path(argv[1]).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    app = create_app()
    schema = app.openapi()
    output.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
