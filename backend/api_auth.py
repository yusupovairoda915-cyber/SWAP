"""FastAPI router for phone login.

NOT RUN YET: fastapi is not installed in my workspace, so this file is only
syntax-checked. The logic (auth.py) is tested.

    from api_auth import router as auth_router
    app.include_router(auth_router)

Server environment: SWAP_SECRET (32+ random chars), and for real SMS SWAP_SMS=eskiz
with ESKIZ_EMAIL / ESKIZ_PASSWORD.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import auth
import sms
from api import get_conn

router = APIRouter(prefix="/auth", tags=["auth"])


def _init(conn=Depends(get_conn)):
    auth.init_schema(conn)
    return conn


class PhoneIn(BaseModel):
    phone: str = Field(max_length=30)


class VerifyIn(BaseModel):
    phone: str = Field(max_length=30)
    code: str = Field(min_length=4, max_length=8)


BAD_PHONE = "Введите номер в формате +998 XX XXX XX XX"


@router.post("/request-code", status_code=204)
def request_code(body: PhoneIn, conn=Depends(_init)):
    try:
        auth.request_code(conn, body.phone, auth.get_secret(), sms.get_sender())
    except auth.InvalidPhone:
        raise HTTPException(422, BAD_PHONE)
    except auth.RateLimited as e:
        raise HTTPException(429, f"Слишком часто. Попробуйте через {e.retry_after} сек.")
    except sms.SmsError:
        raise HTTPException(502, "Не удалось отправить SMS. Попробуйте позже.")


@router.post("/verify")
def verify(body: VerifyIn, conn=Depends(_init)):
    secret = auth.get_secret()
    try:
        user_id, is_new = auth.verify_code(conn, body.phone, body.code, secret)
    except auth.InvalidPhone:
        raise HTTPException(422, BAD_PHONE)
    except auth.InvalidCode:
        raise HTTPException(400, "Неверный или просроченный код")
    return {"token": auth.create_token(user_id, secret), "user_id": user_id, "is_new": is_new}
