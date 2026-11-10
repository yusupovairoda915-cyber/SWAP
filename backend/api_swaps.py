"""FastAPI router for mutual swaps (no credits).

NOT RUN YET: fastapi is not installed in my workspace, so this file is only
syntax-checked. The logic (swaps.py) is tested.

    from api_swaps import router as swaps_router
    app.include_router(swaps_router)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import profiles
import swaps
from api import current_user_id, get_conn

router = APIRouter(prefix="/swaps", tags=["swaps"])


def _init(conn=Depends(get_conn)):
    profiles.init_schema(conn)
    swaps.init_schema(conn)
    return conn


class SwapIn(BaseModel):
    partner_id: str
    i_teach: str = Field(min_length=1, max_length=50)    # skill I teach the partner
    they_teach: str = Field(min_length=1, max_length=50)  # skill the partner teaches me


def _http(e: Exception) -> HTTPException:
    if isinstance(e, swaps.SwapNotFound):
        return HTTPException(404, str(e))
    if isinstance(e, swaps.SwapNotAllowed):
        return HTTPException(403, str(e))
    if isinstance(e, ValueError):
        return HTTPException(422, str(e))
    return HTTPException(409, str(e))


@router.post("", status_code=201)
def propose(body: SwapIn, user_id: str = Depends(current_user_id), conn=Depends(_init)):
    try:
        return {"swap_id": swaps.propose_swap(conn, user_id, body.partner_id, body.i_teach, body.they_teach)}
    except (swaps.SwapError, ValueError) as e:
        raise _http(e)


@router.get("")
def my_swaps(user_id: str = Depends(current_user_id), conn=Depends(_init)):
    return swaps.list_swaps(conn, user_id)


@router.post("/{swap_id}/accept")
def accept(swap_id: int, user_id: str = Depends(current_user_id), conn=Depends(_init)):
    try:
        swaps.accept_swap(conn, swap_id, user_id)
    except swaps.SwapError as e:
        raise _http(e)
    return {"status": "accepted"}


@router.post("/{swap_id}/cancel")
def cancel(swap_id: int, user_id: str = Depends(current_user_id), conn=Depends(_init)):
    try:
        swaps.cancel_swap(conn, swap_id, user_id)
    except swaps.SwapError as e:
        raise _http(e)
    return {"status": "cancelled"}


@router.post("/{swap_id}/confirm")
def confirm(swap_id: int, user_id: str = Depends(current_user_id), conn=Depends(_init)):
    try:
        return {"status": swaps.confirm_swap(conn, swap_id, user_id)}
    except swaps.SwapError as e:
        raise _http(e)
