"""Empty on purpose — supplier adapters do not live here.

This package predates the current layout and holds no vendor code. Every
supplier implements the ``Fulfiller`` protocol in
``yupay.modules.fulfillment.suppliers.base`` and lives in a module beside it,
registered in that package's ``REGISTRY``: g2b, gengine, nova, waxpeer.
``integrations`` owns the SKU-to-supplier *mapping* and the cost sync, not the
adapters themselves. AGENTS.md §4 says the same; both were corrected together
after the table here sent people to a directory that never had anything in it.
"""
