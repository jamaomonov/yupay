"""Transactional outbox.

Producers write a domain row + an ``outbox_messages`` row inside the **same** DB
transaction. A relay actor (see :mod:`yupay.core.outbox.relay`) selects unpublished
messages with ``FOR UPDATE SKIP LOCKED``, dispatches them onto the broker, and marks
them published. Consumers must be idempotent — they check
``processed_events(event_id UNIQUE)`` before acting.
"""
