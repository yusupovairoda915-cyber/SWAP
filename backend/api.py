"""FastAPI router for SWAP credits.

NOT RUN YET: fastapi is not installed in my workspace, so this file is written
carefully but untested. The business logic it calls (ledger.py) IS tested.

Connect it to your app:
    from api import router as credits_router
    app.include_router(credits_router)

Login: see api_auth.py (phone + SMS code). Routes read the token via current_user_id.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

import auth
import ledger
import profiles

router = APIRouter(prefix="/credits", tags=["credits"])


def get_conn():
    conn = ledger.connect(os.getenv("SWAP_DB", "swap.db"))
    try:
        yield conn
    finally:
        conn.close()


def current_user_id(authorization: str | None = Header(default=None)) -> str:
    """Reads 'Authorization: Bearer <token>' (issued by /auth/verify) and returns the user id."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Нужно войти")
    try:
        return auth.verify_token(token, auth.get_secret())
    except auth.InvalidToken:
        raise HTTPException(401, "Сессия истекла, войдите снова")


class BookingIn(BaseModel):
    teacher_id: str
    skill: str = Field(min_length=1, max_length=50)
    hours: int = Field(default=1, ge=1, le=8)
    # The price is NOT sent by the app: the server takes it from the teacher's profile,
    # otherwise a learner could "buy" a lesson for 1 credit.


def _http(e: ledger.CreditsError) -> HTTPException:
    if isinstance(e, ledger.BookingNotFound):
        return HTTPException(404, str(e))
    if isinstance(e, ledger.NotAllowed):
        return HTTPException(403, str(e))
    return HTTPException(409, str(e))  # not enough credits, wrong booking state


@router.get("/wallet")
def wallet(user_id: str = Depends(current_user_id), conn=Depends(get_conn)):
    return ledger.get_wallet(conn, user_id)


@router.get("/history")
def history(limit: int = 50, user_id: str = Depends(current_user_id), conn=Depends(get_conn)):
    return ledger.get_history(conn, user_id, min(limit, 200))


@router.post("/bookings", status_code=201)
def book(body: BookingIn, user_id: str = Depends(current_user_id), conn=Depends(get_conn)):
    profiles.init_schema(conn)
    try:
        price = profiles.get_price(conn, body.teacher_id, body.skill)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if price is None:
        raise HTTPException(422, "this person does not teach this skill")
    credits = price * body.hours
    try:
        booking_id = ledger.book_session(
            conn, user_id, body.teacher_id, credits, profiles.normalize_skill(body.skill)
        )
    except ledger.CreditsError as e:
        raise _http(e)
    return {"booking_id": booking_id, "credits": credits, **ledger.get_wallet(conn, user_id)}


@router.get("/bookings")
def my_bookings(user_id: str = Depends(current_user_id), conn=Depends(get_conn)):
    """My paid lessons (as learner or teacher), with the other person's name."""
    profiles.init_schema(conn)
    rows = ledger.list_bookings(conn, user_id)
    names = profiles.get_names(conn, [r[k] for r in rows for k in ("learner_id", "teacher_id")])
    for r in rows:
        r["learner_name"] = names.get(r["learner_id"], r["learner_id"])
        r["teacher_name"] = names.get(r["teacher_id"], r["teacher_id"])
    return rows


@router.post("/bookings/{booking_id}/complete")
def complete(booking_id: int, user_id: str = Depends(current_user_id), conn=Depends(get_conn)):
    try:
        ledger.complete_booking(conn, booking_id, user_id)
    except ledger.CreditsError as e:
        raise _http(e)
    return {"status": "completed"}


@router.post("/bookings/{booking_id}/cancel")
def cancel(booking_id: int, user_id: str = Depends(current_user_id), conn=Depends(get_conn)):
    try:
        ledger.cancel_booking(conn, booking_id, user_id)
    except ledger.CreditsError as e:
        raise _http(e)
    return {"status": "cancelled"}
