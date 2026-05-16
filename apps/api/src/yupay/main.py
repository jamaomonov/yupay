"""FastAPI HTTP application entrypoint.

Composition is delegated to :func:`yupay.bootstrap.create_app` so tests can build
isolated app instances.
"""

from __future__ import annotations

from yupay.bootstrap import create_app

app = create_app()
