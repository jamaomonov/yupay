"""Per-module Dramatiq actor packages.

Add a new file ``tasks/<module>.py`` whenever a domain module needs background work.
Actors must be idempotent and accept an ``idempotency_key`` argument where applicable.
"""
