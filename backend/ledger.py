"""SWAP credits: ledger-based wallets with escrow for skill-exchange sessions.

Idea: 1 credit ~ 1 hour of teaching. A learner books a session -> credits are
held (taken from the learner). When the learner confirms the session happened,
the teacher receives them. If it is cancelled, the learner gets a refund.

Rules that keep the money safe:
- integer credits only (no floats, no rounding bugs);
- every change is a row in `ledger` (append-only history);
- every operation runs in one transaction (all or nothing);
- balance can never go below zero (CHECK constraint + explicit check).

Pure standard library (sqlite3). The SQL is plain, so moving to PostgreSQL later
only means swapping `?` placeholders for `%s` / `:name` and AUTOINCREMENT for
SERIAL / IDENTITY.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

WELCOME_BONUS = 3  # free credits for every new user so they can take a first lesson

SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets (
    user_id TEXT PRIMARY KEY,
    balance INTEGER NOT NULL DEFAULT 0 CHECK (balance >= 0)
);

CREATE TABLE IF NOT EXISTS bookings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id   TEXT NOT NULL,
    teacher_id   TEXT NOT NULL,
    skill        TEXT NOT NULL DEFAULT '',
    credits      INTEGER NOT NULL CHECK (credits > 0),
    status       TEXT NOT NULL DEFAULT 'held'
                 CHECK (status IN ('held', 'completed', 'cancelled')),
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at  TEXT
);

CREATE TABLE IF NOT EXISTS ledger (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    amount     INTEGER NOT NULL,           -- + income, - spending
    kind       TEXT NOT NULL,              -- welcome_bonus | hold | earn | refund
    booking_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ledger_user ON ledger (user_id, id);
"""


class CreditsError(Exception):
    """Base class for all expected business errors."""


class InsufficientCredits(CreditsError):
    pass


class BookingNotFound(CreditsError):
    pass


class InvalidBookingState(CreditsError):
    pass


class NotAllowed(CreditsError):
    pass


def connect(path: str = "swap.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def _tx(conn: sqlite3.Connection):
    """One atomic transaction. IMMEDIATE takes the write lock up front, so two
    simultaneous bookings can't both spend the same credits."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _post(conn, user_id: str, amount: int, kind: str, booking_id: int | None = None) -> None:
    """Change a balance and write the ledger row together (call inside _tx)."""
    cur = conn.execute(
        "UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (amount, user_id)
    )
    if cur.rowcount == 0:
        raise CreditsError(f"wallet not found for user {user_id}")
    conn.execute(
        "INSERT INTO ledger (user_id, amount, kind, booking_id) VALUES (?, ?, ?, ?)",
        (user_id, amount, kind, booking_id),
    )


def _booking(conn, booking_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if row is None:
        raise BookingNotFound(f"booking {booking_id} not found")
    return row


# ---------------------------------------------------------------- wallets

def ensure_wallet(conn, user_id: str) -> None:
    """Create the wallet (and give the welcome bonus) once. Safe to call many times."""
    with _tx(conn):
        cur = conn.execute("INSERT OR IGNORE INTO wallets (user_id) VALUES (?)", (user_id,))
        if cur.rowcount:
            _post(conn, user_id, WELCOME_BONUS, "welcome_bonus")


def get_wallet(conn, user_id: str) -> dict:
    """available = can be spent now; held = locked in active bookings."""
    ensure_wallet(conn, user_id)
    available = conn.execute(
        "SELECT balance FROM wallets WHERE user_id = ?", (user_id,)
    ).fetchone()["balance"]
    held = conn.execute(
        "SELECT COALESCE(SUM(credits), 0) AS s FROM bookings "
        "WHERE learner_id = ? AND status = 'held'",
        (user_id,),
    ).fetchone()["s"]
    return {"user_id": user_id, "available": available, "held": held}


def get_history(conn, user_id: str, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT id, amount, kind, booking_id, created_at FROM ledger "
        "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------- bookings

def book_session(conn, learner_id: str, teacher_id: str, credits: int, skill: str = "") -> int:
    """Learner books a session: credits leave the learner's balance and are held."""
    if credits <= 0:
        raise ValueError("credits must be positive")
    if learner_id == teacher_id:
        raise NotAllowed("you cannot book your own session")

    ensure_wallet(conn, learner_id)
    ensure_wallet(conn, teacher_id)

    with _tx(conn):
        balance = conn.execute(
            "SELECT balance FROM wallets WHERE user_id = ?", (learner_id,)
        ).fetchone()["balance"]
        if balance < credits:
            raise InsufficientCredits(f"need {credits}, available {balance}")
        cur = conn.execute(
            "INSERT INTO bookings (learner_id, teacher_id, credits, skill) VALUES (?, ?, ?, ?)",
            (learner_id, teacher_id, credits, skill),
        )
        booking_id = cur.lastrowid
        _post(conn, learner_id, -credits, "hold", booking_id)
    return booking_id


def complete_booking(conn, booking_id: int, user_id: str) -> None:
    """Only the learner confirms. The teacher is paid."""
    with _tx(conn):
        b = _booking(conn, booking_id)
        if user_id != b["learner_id"]:
            raise NotAllowed("only the learner can confirm the session")
        if b["status"] != "held":
            raise InvalidBookingState(f"booking is already {b['status']}")
        _post(conn, b["teacher_id"], b["credits"], "earn", booking_id)
        conn.execute(
            "UPDATE bookings SET status = 'completed', finished_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (booking_id,),
        )


def cancel_booking(conn, booking_id: int, user_id: str) -> None:
    """Learner or teacher cancels an active booking. The learner gets credits back."""
    with _tx(conn):
        b = _booking(conn, booking_id)
        if user_id not in (b["learner_id"], b["teacher_id"]):
            raise NotAllowed("you are not part of this booking")
        if b["status"] != "held":
            raise InvalidBookingState(f"booking is already {b['status']}")
        _post(conn, b["learner_id"], b["credits"], "refund", booking_id)
        conn.execute(
            "UPDATE bookings SET status = 'cancelled', finished_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (booking_id,),
        )


def list_bookings(conn, user_id: str, limit: int = 50) -> list[dict]:
    """Paid lessons where the user is the learner or the teacher, newest first."""
    rows = conn.execute(
        "SELECT id, learner_id, teacher_id, skill, credits, status, created_at, finished_at "
        "FROM bookings WHERE learner_id = ? OR teacher_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, user_id, max(1, min(limit, 200))),
    ).fetchall()
    return [dict(r) for r in rows]
