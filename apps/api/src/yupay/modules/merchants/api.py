"""Public interface of the ``merchants`` module.

Other modules import from here, never from ``models`` or a future
``service``/``routes`` directly — the same rule the rest of the codebase
follows. Empty for now: this task only lays the schema. Account creation,
API-key issuance, and cabinet auth land in later tasks and get re-exported
here as they arrive.
"""

from __future__ import annotations

__all__: list[str] = []
