"""SWAP login by phone number: SMS code -> signed token.

Flow:
  1. App sends the phone number  -> request_code() makes a 6-digit code and sends it by SMS.
  2. User types the code         -> verify_code() checks it and returns (user_id, is_new).
  3. Server hands out a token    -> create_token(); every later request carries it
     as  "Authorization: Bearer <token>"  and verify_token() gives back the user_id.

Safety built in:
  - codes are stored only as an HMAC hash, live 5 minutes, work once;
  - 5 wrong attempts burn the code;
  - one SMS per phone per 60 seconds and at most 5 per hour (SMS costs money);
  - tokens are HS256 JWT signed with SWAP_SECRET (32+ random characters, set it in the
    server environment; without it the server refuses to start login).

Pure standard library. Time is passed in (`now`) so tests don't need to wait.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import uuid

import ledger

CODE_TTL = 300          # code lives 5 minutes
MAX_ATTEMPTS = 5        # wrong tries per code
RESEND_AFTER = 60       # seconds between SMS to one phone
MAX_SENDS_PER_HOUR = 5
TOKEN_TTL = 30 * 24 * 3600

SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_users (
    user_id    TEXT PRIMARY KEY,
    phone      TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS otp (
    phone      TEXT PRIMARY KEY,
    code_hash  TEXT NOT NULL,
    expires_at REAL NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS otp_sends (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    phone   TEXT NOT NULL,
    sent_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_otp_sends ON otp_sends (phone, sent_at);
"""


class AuthError(Exception):
    pass


class InvalidPhone(AuthError):
    pass


class InvalidCode(AuthError):
    pass


class InvalidToken(AuthError):
    pass


class RateLimited(AuthError):
    def __init__(self, retry_after: int):
        super().__init__(f"try again in {retry_after}s")
        self.retry_after = retry_after


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def get_secret() -> str:
    s = os.environ.get("SWAP_SECRET", "")
    if len(s) < 32:
        raise RuntimeError("Set SWAP_SECRET in the server environment (32+ random characters)")
    return s


# ------------------------------------------------------------------ phone

def normalize_phone(raw: str) -> str:
    """Uzbek numbers only for now: returns '+998XXXXXXXXX' or raises InvalidPhone.
    Accepts '+998 90 123 45 67', '998901234567', '90 123 45 67' ..."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 9:
        digits = "998" + digits
    if not re.fullmatch(r"998\d{9}", digits):
        raise InvalidPhone("phone must be an Uzbek number: +998 XX XXX XX XX")
    return "+" + digits


def _hash_code(secret: str, phone: str, code: str) -> str:
    return hmac.new(secret.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


# -------------------------------------------------------------- send code

def request_code(conn, phone: str, secret: str, sender, now: float | None = None) -> None:
    """Create a code and SMS it. `sender` is any object with .send(phone, text)."""
    now = time.time() if now is None else now
    phone = normalize_phone(phone)
    code = f"{secrets.randbelow(1_000_000):06d}"

    with ledger._tx(conn):
        last = conn.execute(
            "SELECT MAX(sent_at) AS t FROM otp_sends WHERE phone = ?", (phone,)
        ).fetchone()["t"]
        if last is not None and now - last < RESEND_AFTER:
            raise RateLimited(int(RESEND_AFTER - (now - last)) + 1)
        sent = conn.execute(
            "SELECT COUNT(*) AS c FROM otp_sends WHERE phone = ? AND sent_at > ?",
            (phone, now - 3600),
        ).fetchone()["c"]
        if sent >= MAX_SENDS_PER_HOUR:
            raise RateLimited(3600)
        conn.execute(
            "INSERT INTO otp (phone, code_hash, expires_at, attempts) VALUES (?, ?, ?, 0) "
            "ON CONFLICT(phone) DO UPDATE SET code_hash = excluded.code_hash, "
            "expires_at = excluded.expires_at, attempts = 0",
            (phone, _hash_code(secret, phone, code), now + CODE_TTL),
        )
        conn.execute("INSERT INTO otp_sends (phone, sent_at) VALUES (?, ?)", (phone, now))
        conn.execute("DELETE FROM otp_sends WHERE sent_at < ?", (now - 86400,))

    # network call AFTER the transaction, so the database is not locked while we wait
    sender.send(phone, f"SWAP: ваш код {code}. Никому его не сообщайте.")


# ------------------------------------------------------------ check code

def verify_code(conn, phone: str, code: str, secret: str, now: float | None = None) -> tuple[str, bool]:
    """Returns (user_id, is_new). Raises InvalidCode for wrong / expired / used / locked codes."""
    now = time.time() if now is None else now
    phone = normalize_phone(phone)
    code = (code or "").strip()

    failed = False
    user_id, is_new = "", False
    with ledger._tx(conn):
        row = conn.execute("SELECT * FROM otp WHERE phone = ?", (phone,)).fetchone()
        if row is None:
            failed = True
        elif row["expires_at"] < now or row["attempts"] >= MAX_ATTEMPTS:
            conn.execute("DELETE FROM otp WHERE phone = ?", (phone,))
            failed = True
        elif not hmac.compare_digest(row["code_hash"], _hash_code(secret, phone, code)):
            attempts = row["attempts"] + 1
            if attempts >= MAX_ATTEMPTS:
                conn.execute("DELETE FROM otp WHERE phone = ?", (phone,))
            else:
                conn.execute("UPDATE otp SET attempts = ? WHERE phone = ?", (attempts, phone))
            failed = True
        else:
            conn.execute("DELETE FROM otp WHERE phone = ?", (phone,))  # single use
            u = conn.execute("SELECT user_id FROM auth_users WHERE phone = ?", (phone,)).fetchone()
            if u:
                user_id = u["user_id"]
            else:
                user_id, is_new = uuid.uuid4().hex, True
                conn.execute(
                    "INSERT INTO auth_users (user_id, phone, created_at) VALUES (?, ?, ?)",
                    (user_id, phone, now),
                )
    # raise only after the transaction ended: raising inside would roll back the attempt counter
    if failed:
        raise InvalidCode("wrong or expired code")
    return user_id, is_new


# ----------------------------------------------------------------- tokens

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: str, signing_input: str) -> str:
    return _b64(hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest())


def create_token(user_id: str, secret: str, now: float | None = None, ttl: int = TOKEN_TTL) -> str:
    now = time.time() if now is None else now
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps(
        {"sub": user_id, "iat": int(now), "exp": int(now + ttl)}, separators=(",", ":")
    ).encode())
    signing_input = f"{header}.{payload}"
    return f"{signing_input}.{_sign(secret, signing_input)}"


def verify_token(token: str, secret: str, now: float | None = None) -> str:
    """Returns the user_id or raises InvalidToken."""
    now = time.time() if now is None else now
    try:
        header_b64, payload_b64, sig = token.split(".")
        header = json.loads(_unb64(header_b64))
        if header.get("alg") != "HS256":  # blocks the classic "alg: none" trick
            raise InvalidToken("bad algorithm")
        if not hmac.compare_digest(sig, _sign(secret, f"{header_b64}.{payload_b64}")):
            raise InvalidToken("bad signature")
        payload = json.loads(_unb64(payload_b64))
        if not isinstance(payload.get("sub"), str) or payload["exp"] <= now:
            raise InvalidToken("expired")
        return payload["sub"]
    except InvalidToken:
        raise
    except Exception as e:  # garbage input of any kind
        raise InvalidToken("malformed token") from e
