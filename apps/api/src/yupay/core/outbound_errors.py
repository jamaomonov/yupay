"""What :func:`yupay.core.outbound.post_json` raises, and nothing else.

The taxonomy is the caller's half of the contract — `apps/worker`'s drain
decides a delivery outcome by catching these — so it lives in its own module,
importable without the client and readable without the transport around it.
:mod:`yupay.core.outbound` re-exports every name here; import from either.

Two families and one flag:

- :class:`OutboundRefusedError` — the attempt ended on **our** side.
- :class:`OutboundUnreachableError` — it ended on **theirs**.
- :attr:`OutboundError.attempt_delivered` — whether the request nonetheless
  reached them, which is what decides if a retry is safe. It is a flag rather
  than a third family so that a caller matching the two families cannot miss a
  branch.
"""

from __future__ import annotations

from typing import ClassVar


class OutboundError(Exception):
    """Base class for everything :func:`post_json` raises.

    Nothing else can escape it: every path out of :func:`post_json` is either
    one of these or re-raised as one with the original chained on
    ``__cause__``. The caller is a queue drain that decides an outcome by
    catching this base, and an untyped exception there is a claimed row that
    never reaches a terminal state and is re-claimed forever.

    Attributes:
        attempt_delivered: Whether the request reached their server before the
            failure. Read **this**, not the class, when deciding whether a
            retry is safe: ``True`` means a retry re-delivers.
    """

    attempt_delivered: ClassVar[bool] = False


class OutboundRefusedError(OutboundError):
    """The attempt ended **on our side**: we would not, or could not, complete it.

    Their server did not reject anything. Retrying changes nothing until the
    input changes — a different URL, different DNS, or a smaller response.
    Whether they nonetheless *received* the request is
    :attr:`OutboundError.attempt_delivered`, which is true for the two
    children that refuse an *answer* rather than a destination; that flag is
    why the family stays two-wide instead of growing a third branch a caller
    could forget to catch.
    """


class UrlNotAllowedError(OutboundRefusedError):
    """The URL was refused before anything was resolved or connected to.

    Also covers a URL no request could be built from at all — an IDN label
    that will not encode, a header value that cannot go on the wire. Those are
    as much "we will not send to this" as a plain ``http://`` is, and the
    caller needs one answer, not two. (An over-long **ASCII** label is a
    :class:`ResolutionFailedError` instead: nothing rejects it until the
    lookup does.)
    """


class AddressNotAllowedError(OutboundRefusedError):
    """A resolved address is not one we will connect to.

    Attributes:
        host: The hostname that resolved to it.
        reasons: One ``"<address>: <family>"`` string per offending answer.
    """

    def __init__(self, message: str, *, host: str = "", reasons: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.host = host
        self.reasons = reasons


class ResponseTooLargeError(OutboundRefusedError):
    """The response passed ``max_bytes`` and the read was cut off.

    The odd one out, and the reason :attr:`OutboundError.attempt_delivered`
    exists: their server **received** the delivery and answered it, so a retry
    re-delivers. Terminal, not retryable.
    """

    attempt_delivered: ClassVar[bool] = True


class ContentEncodingNotAllowedError(OutboundRefusedError):
    """They answered with a compressed body, which we do not decode.

    We ask for ``identity`` and read the wire bytes with a cap on them, so a
    compression bomb cannot expand past that cap inside this process. What we
    will not do is hand a caller a body we never decoded and let it be read as
    text, so an encoded response is a refusal rather than a garbled success.
    Like :class:`ResponseTooLargeError` it means the delivery landed.
    """

    attempt_delivered: ClassVar[bool] = True


class OutboundBrokenError(OutboundRefusedError):
    """The attempt broke in a way neither side chose — i.e. our bug.

    The catch-all that keeps :class:`OutboundError` total. It sits under
    "ended on our side" rather than under "they did not answer" on purpose: an
    unexpected exception is deterministic in its input, so retrying it walks a
    merchant's endpoint into an auto-disable for a fault that is ours.
    ``__cause__`` carries the original, and it is logged with a stack.
    """


class OutboundUnreachableError(OutboundError):
    """The attempt ended **on their side**: nobody answered. A retry may work."""


class ResolutionFailedError(OutboundUnreachableError):
    """The hostname did not resolve at all."""


class ConnectFailedError(OutboundUnreachableError):
    """The connection, the TLS handshake, or the exchange itself failed."""


class OutboundTimeoutError(OutboundUnreachableError):
    """The attempt passed its total wall-clock budget."""


__all__ = [
    "AddressNotAllowedError",
    "ConnectFailedError",
    "ContentEncodingNotAllowedError",
    "OutboundBrokenError",
    "OutboundError",
    "OutboundRefusedError",
    "OutboundTimeoutError",
    "OutboundUnreachableError",
    "ResolutionFailedError",
    "ResponseTooLargeError",
    "UrlNotAllowedError",
]
