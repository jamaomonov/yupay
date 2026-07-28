"""HTTP + WebSocket routes for realtime order updates."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket
from pydantic import BaseModel

from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.auth import jwt as authjwt
from yupay.modules.auth.deps import current_user
from yupay.modules.realtime.service import run_order_socket
from yupay.modules.users.models import User

log = get_logger("yupay.realtime.routes")

router = APIRouter(prefix="/realtime", tags=["realtime"])


class HandshakeOut(BaseModel):
    """Response body for a successful WS handshake mint."""

    token: str


@router.post("/handshake", response_model=HandshakeOut, summary="Mint a 60s WS handshake token")
async def handshake(user: Annotated[User, Depends(current_user)]) -> HandshakeOut:
    """Mint a short-lived ``ws``-kind token the caller exchanges for a socket connection."""
    token = authjwt.mint_ws_handshake(sub=user.id, sid=new_id(), channel=f"user:{user.id}")
    return HandshakeOut(token=token)


@router.websocket("/ws/orders")
async def ws_orders(websocket: WebSocket, token: str) -> None:
    """Verify the handshake token and, on success, run the order-updates socket."""
    try:
        claims = authjwt.verify(token, expected_kind="ws")
    except Exception as exc:  # noqa: BLE001 -- any verify failure closes the handshake
        # Log the cause (not the token, a credential) so a real bug — e.g. an
        # unconfigured JWT_PUBLIC_KEY raising RuntimeError — leaves a trace instead
        # of being indistinguishable from a client sending a bad/expired token.
        log.warning("realtime.ws.auth_failed", error=str(exc))
        await websocket.close(code=4401)
        return
    await run_order_socket(websocket, claims.sub)
