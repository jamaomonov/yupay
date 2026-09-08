"""What :func:`yupay.core.outbound.post_json` raises, and nothing else.

The taxonomy is the caller's half of the contract — `apps/worker`'s drain
decides a delivery outcome by catching these — so it lives in its own module,
importable without the client and readable without the transport around it.
:mod:`yupay.core.outbound` re-exports every name here; import from either.

Two families and one three-valued fact:

- :class:`OutboundRefusedError` — the attempt ended on **our** side.
- :class:`OutboundUnreachableError` — it ended on **theirs**.
- :attr:`OutboundError.delivery` — whether their server got the request. It is
  three-valued because two of the three answers are not "no": a boolean here
  collapses "nothing was sent" into the same bucket as "it was sent and we
  never heard back", and a retry policy reading that boolean re-delivers a
  webhook to a merchant who answered eleven seconds into a ten-second budget.
  The families stay two-wide so a caller matching on them cannot miss a
  branch; the delivery question is answered by this attribute, not by the
  class.

Every leaf declares its own :attr:`~OutboundError.delivery`, and a test walks
``OutboundError.__subclasses__()`` to insist on it — a new leaf cannot be
added without deciding what it means for a retry.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar


class Delivery(StrEnum):
    """What is known about whether the merchant's server got the request.

    Attributes:
        NOT_SENT: Nothing left this process for their server. Safe to retry.
        UNKNOWN: The request went out and the outcome is not known. A retry
            may deliver a second copy; whether that is acceptable is the
            caller's call, not this module's.
        RECEIVED: Their server took the request and answered. A retry
            **re-delivers**.
    """

    NOT_SENT = "not_sent"
    UNKNOWN = "unknown"
    RECEIVED = "received"


class OutboundError(Exception):
    """Base class for everything :func:`post_json` raises.

    Nothing else can escape it: every path out of :func:`post_json` is either
    one of these or re-raised as one with the original chained on
    ``__cause__``. The caller is a queue drain that decides an outcome by
    catching this base, and an untyped exception there is a claimed row that
    never reaches a terminal state and is re-claimed forever.

    Attributes:
        delivery: What is known about the request reaching their server. The
            default is :attr:`Delivery.UNKNOWN` — the conservative answer, so
            a leaf that forgets to decide errs towards "might have been
            delivered" rather than towards a blind retry.
    """

    delivery: ClassVar[Delivery] = Delivery.UNKNOWN


class OutboundRefusedError(OutboundError):
    """The attempt ended **on our side**: we would not, or could not, complete it.

    Their server did not reject anything. Retrying changes nothing until the
    input changes — a different URL, different DNS, or a smaller response.
    Whether they nonetheless *received* the request is
    :attr:`OutboundError.delivery`, which is :attr:`Delivery.RECEIVED` for the
    two children that refuse an *answer* rather than a destination.
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

    delivery: ClassVar[Delivery] = Delivery.NOT_SENT


class AddressNotAllowedError(OutboundRefusedError):
    """A resolved address is not one we will connect to.

    Attributes:
        host: The hostname that resolved to it.
        reasons: One ``"<address>: <family>"`` string per offending answer.
    """

    delivery: ClassVar[Delivery] = Delivery.NOT_SENT

    def __init__(self, message: str, *, host: str = "", reasons: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.host = host
        self.reasons = reasons


class ResponseTooLargeError(OutboundRefusedError):
    """The response passed ``max_bytes`` and the read was cut off.

    One of the two refusals that mean the delivery landed: their server
    received it and answered, so a retry re-delivers. Terminal.
    """

    delivery: ClassVar[Delivery] = Delivery.RECEIVED


class ContentEncodingNotAllowedError(OutboundRefusedError):
    """They answered with a compressed body, which we do not decode.

    We ask for ``identity`` and read the wire bytes with a cap on them, so a
    compression bomb cannot expand past that cap inside this process. What we
    will not do is hand a caller a body we never decoded and let it be read as
    text, so an encoded response is a refusal rather than a garbled success.
    Like :class:`ResponseTooLargeError` it means the delivery landed.
    """

    delivery: ClassVar[Delivery] = Delivery.RECEIVED


class OutboundBrokenError(OutboundRefusedError):
    """The attempt broke in a way neither side chose — i.e. our bug.

    The catch-all that keeps :class:`OutboundError` total. It sits under
    "ended on our side" rather than under "they did not answer" on purpose: an
    unexpected exception is deterministic in its input, so retrying it walks a
    merchant's endpoint into an auto-disable for a fault that is ours.
    ``__cause__`` carries the original.

    **The caller must not count this toward a merchant's failure budget.** It
    is in the refusal family because forgetting the branch should mean "we
    blame ourselves", but the special case moved rather than disappeared: a
    bug of ours must not auto-disable a working endpoint and show in the
    merchant's log as "we refused your URL".

    Its delivery is :attr:`Delivery.UNKNOWN` and not ``NOT_SENT``, because the
    net covers the whole call and cannot know where inside it the break
    happened.
    """

    delivery: ClassVar[Delivery] = Delivery.UNKNOWN


class OutboundUnreachableError(OutboundError):
    """The attempt ended **on their side**: nobody answered. A retry may work."""


class ResolutionFailedError(OutboundUnreachableError):
    """The hostname did not resolve at all."""

    delivery: ClassVar[Delivery] = Delivery.NOT_SENT


class ConnectFailedError(OutboundUnreachableError):
    """The TCP connection or the TLS handshake never came up.

    Nothing was written, so this is the one transport failure that is safe to
    retry blindly. A failure *after* the connection came up is
    :class:`ExchangeFailedError`, which is not.
    """

    delivery: ClassVar[Delivery] = Delivery.NOT_SENT


class ExchangeFailedError(OutboundUnreachableError):
    """The connection came up and the exchange broke — a reset, a bad framing.

    Split from :class:`ConnectFailedError` because the request may already
    have been written and processed by then. Same family, different answer to
    the only question a retry policy needs to ask.
    """

    delivery: ClassVar[Delivery] = Delivery.UNKNOWN


class OutboundTimeoutError(OutboundUnreachableError):
    """The attempt passed its total wall-clock budget.

    ``UNKNOWN``, not ``NOT_SENT``: the live suite's timeout case asserts the
    server **did** receive the request and simply never answered, which is the
    ordinary shape of a timeout. A merchant answering in eleven seconds
    against a ten-second budget has already provisioned the order.
    """

    delivery: ClassVar[Delivery] = Delivery.UNKNOWN


__all__ = [
    "AddressNotAllowedError",
    "ConnectFailedError",
    "ContentEncodingNotAllowedError",
    "Delivery",
    "ExchangeFailedError",
    "OutboundBrokenError",
    "OutboundError",
    "OutboundRefusedError",
    "OutboundTimeoutError",
    "OutboundUnreachableError",
    "ResolutionFailedError",
    "ResponseTooLargeError",
    "UrlNotAllowedError",
]
