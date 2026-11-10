"""SWAP mutual swaps: two people teach each other, no credits involved.

Flow:
  1. A proposes to B: "I teach you <skill_a>, you teach me <skill_b>".
  2. B accepts (or either side cancels / B declines).
  3. After the lessons each person confirms. When BOTH confirmed -> completed.

Only real mutual swaps are allowed: A must teach skill_a and B must want it;
B must teach skill_b and A must want it (same data as profiles.find_swap_matches).

Lives in its own table, so the credits tables (ledger.py) are untouched.
Call ledger.connect(), profiles.init_schema(conn) and swaps.init_schema(conn) once.
"""
from __future__ import annotations

import sqlite3

import ledger
import profiles

SCHEMA = """
CREATE TABLE IF NOT EXISTS swaps (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_a     TEXT NOT NULL,              -- proposer
    user_b     TEXT NOT NULL,
    skill_a    TEXT NOT NULL,              -- what A teaches B
    skill_b    TEXT NOT NULL,              -- what B teaches A
    status     TEXT NOT NULL DEFAULT 'proposed'
               CHECK (status IN ('proposed', 'accepted', 'completed', 'cancelled')),
    a_done     INTEGER NOT NULL DEFAULT 0,
    b_done     INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_swaps_a ON swaps (user_a, status);
CREATE INDEX IF NOT EXISTS idx_swaps_b ON swaps (user_b, status);
"""


class SwapError(Exception):
    pass


class SwapNotFound(SwapError):
    pass


class SwapNotAllowed(SwapError):
    pass


class SwapInvalidState(SwapError):
    pass


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _has(conn, user_id: str, skill: str, kind: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM user_skills WHERE user_id = ? AND skill = ? AND kind = ?",
        (user_id, skill, kind),
    ).fetchone() is not None


def _get(conn, swap_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM swaps WHERE id = ?", (swap_id,)).fetchone()
    if row is None:
        raise SwapNotFound(f"swap {swap_id} not found")
    return row


def propose_swap(conn, user_a: str, user_b: str, skill_a: str, skill_b: str) -> int:
    if user_a == user_b:
        raise SwapNotAllowed("you cannot swap with yourself")
    skill_a = profiles.normalize_skill(skill_a)
    skill_b = profiles.normalize_skill(skill_b)

    with ledger._tx(conn):
        if not (_has(conn, user_a, skill_a, "teach") and _has(conn, user_b, skill_a, "learn")):
            raise SwapNotAllowed(f"'{skill_a}': you must teach it and the other person must want it")
        if not (_has(conn, user_b, skill_b, "teach") and _has(conn, user_a, skill_b, "learn")):
            raise SwapNotAllowed(f"'{skill_b}': the other person must teach it and you must want it")
        dup = conn.execute(
            "SELECT 1 FROM swaps WHERE status IN ('proposed', 'accepted') AND "
            "((user_a = ? AND user_b = ? AND skill_a = ? AND skill_b = ?) OR "
            " (user_a = ? AND user_b = ? AND skill_a = ? AND skill_b = ?))",
            (user_a, user_b, skill_a, skill_b, user_b, user_a, skill_b, skill_a),
        ).fetchone()
        if dup:
            raise SwapInvalidState("this swap is already active")
        cur = conn.execute(
            "INSERT INTO swaps (user_a, user_b, skill_a, skill_b) VALUES (?, ?, ?, ?)",
            (user_a, user_b, skill_a, skill_b),
        )
        return cur.lastrowid


def accept_swap(conn, swap_id: int, user_id: str) -> None:
    with ledger._tx(conn):
        s = _get(conn, swap_id)
        if user_id != s["user_b"]:
            raise SwapNotAllowed("only the invited person can accept")
        if s["status"] != "proposed":
            raise SwapInvalidState(f"swap is already {s['status']}")
        conn.execute(
            "UPDATE swaps SET status = 'accepted', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (swap_id,),
        )


def cancel_swap(conn, swap_id: int, user_id: str) -> None:
    """Either side may cancel while the swap is proposed or accepted (B uses it to decline)."""
    with ledger._tx(conn):
        s = _get(conn, swap_id)
        if user_id not in (s["user_a"], s["user_b"]):
            raise SwapNotAllowed("you are not part of this swap")
        if s["status"] not in ("proposed", "accepted"):
            raise SwapInvalidState(f"swap is already {s['status']}")
        conn.execute(
            "UPDATE swaps SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (swap_id,),
        )


def confirm_swap(conn, swap_id: int, user_id: str) -> str:
    """Each person confirms their part is done. Returns the new status."""
    with ledger._tx(conn):
        s = _get(conn, swap_id)
        if user_id not in (s["user_a"], s["user_b"]):
            raise SwapNotAllowed("you are not part of this swap")
        if s["status"] != "accepted":
            raise SwapInvalidState(f"swap is {s['status']}, only accepted swaps can be confirmed")
        col = "a_done" if user_id == s["user_a"] else "b_done"
        conn.execute(f"UPDATE swaps SET {col} = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (swap_id,))
        s = _get(conn, swap_id)
        if s["a_done"] and s["b_done"]:
            conn.execute("UPDATE swaps SET status = 'completed' WHERE id = ?", (swap_id,))
            return "completed"
        return "accepted"


def list_swaps(conn, user_id: str, limit: int = 50) -> list[dict]:
    """My swaps, newest first. Includes both people's names (name_a, name_b)."""
    rows = conn.execute(
        "SELECT s.*, pa.name AS name_a, pb.name AS name_b "
        "FROM swaps s "
        "LEFT JOIN profiles pa ON pa.user_id = s.user_a "
        "LEFT JOIN profiles pb ON pb.user_id = s.user_b "
        "WHERE s.user_a = ? OR s.user_b = ? ORDER BY s.id DESC LIMIT ?",
        (user_id, user_id, max(1, min(limit, 200))),
    ).fetchall()
    return [dict(r) for r in rows]
