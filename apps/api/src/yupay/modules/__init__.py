"""Domain modules.

Each module owns its own tables and exposes a narrow public interface via ``api.py``.
**Never** import internals (models, schemas, services) of one module from another; call
``api.py`` or react to outbox events.
"""
