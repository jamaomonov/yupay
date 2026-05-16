"""Provider webhook routes.

Mounted at ``/webhooks/<provider>``. **No** API versioning — providers don't talk versions;
they talk URLs we've registered with them. Signature verification is mandatory before
parsing the body.
"""
