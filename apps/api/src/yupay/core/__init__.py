"""Shared kernel — utilities and infrastructure used by every module.

Nothing in ``core`` may import from ``yupay.modules``. Direction is one-way:
modules depend on core, never the reverse.
"""
