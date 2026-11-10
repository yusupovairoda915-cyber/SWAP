"""SWAP profiles, skills and teacher search.

A user has a profile (name, city, bio) and a list of skills. Each skill is either
'teach' (I can teach it, with a price in credits per hour) or 'learn' (I want to learn it).

Search: find teachers of a skill, optionally in a city, cheapest first.
Skill names are normalized ("  Python ", "python" -> "python"), so spelling
differences in case and spaces don't split the same skill into two.

Uses the same sqlite connection style as ledger.py (call ledger.connect first,
then init_schema(conn) once).
"""
from __future__ import annotations

import re
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    user_id TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    city    TEXT NOT NULL DEFAULT '',
    city_key TEXT NOT NULL DEFAULT '',   -- lowercase city for search (SQLite lower() ignores Cyrillic)
    bio     TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS user_skills (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       TEXT NOT NULL,
    skill         TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('teach', 'learn')),
    price         INTEGER CHECK (price IS NULL OR price > 0),  -- credits/hour, teach only
    UNIQUE (user_id, skill, kind)
);
CREATE INDEX IF NOT EXISTS idx_skills_search ON user_skills (skill, kind);
"""

MAX_SKILLS_PER_USER = 30


class ProfileError(Exception):
    pass


class ProfileNotFound(ProfileError):
    pass


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def normalize_skill(name: str) -> str:
    s = re.sub(r"\s+", " ", name.strip().lower())
    if not s or len(s) > 50:
        raise ValueError("skill name must be 1-50 characters")
    return s


def _clean(text: str, limit: int) -> str:
    return text.strip()[:limit]


def city_key(city: str) -> str:
    return re.sub(r"\s+", " ", city.strip()).casefold()


# ---------------------------------------------------------------- profile

def save_profile(conn, user_id: str, name: str, city: str = "", bio: str = "") -> dict:
    name = _clean(name, 60)
    if not name:
        raise ValueError("name is required")
    city = _clean(city, 60)
    bio = _clean(bio, 500)
    conn.execute(
        "INSERT INTO profiles (user_id, name, city, city_key, bio) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET name = excluded.name, "
        "city = excluded.city, city_key = excluded.city_key, bio = excluded.bio",
        (user_id, name, city, city_key(city), bio),
    )
    return get_profile(conn, user_id)


def get_profile(conn, user_id: str) -> dict:
    row = conn.execute(
        "SELECT user_id, name, city, bio FROM profiles WHERE user_id = ?", (user_id,)
    ).fetchone()
    if row is None:
        raise ProfileNotFound(f"profile {user_id} not found")
    skills = conn.execute(
        "SELECT skill, kind, price FROM user_skills WHERE user_id = ? ORDER BY kind, skill",
        (user_id,),
    ).fetchall()
    return {
        **dict(row),
        "teach": [{"skill": s["skill"], "price": s["price"]} for s in skills if s["kind"] == "teach"],
        "learn": [s["skill"] for s in skills if s["kind"] == "learn"],
    }


# ----------------------------------------------------------------- skills

def add_skill(conn, user_id: str, skill: str, kind: str, price: int | None = None) -> None:
    """Add (or update the price of) a skill. A teach skill needs a price, a learn skill must not have one."""
    if conn.execute("SELECT 1 FROM profiles WHERE user_id = ?", (user_id,)).fetchone() is None:
        raise ProfileNotFound("create your profile first")
    skill = normalize_skill(skill)
    if kind == "teach":
        if price is None or price <= 0 or price > 100:
            raise ValueError("price for a teach skill must be 1-100 credits per hour")
    elif kind == "learn":
        price = None
    else:
        raise ValueError("kind must be 'teach' or 'learn'")

    count = conn.execute(
        "SELECT COUNT(*) AS c FROM user_skills WHERE user_id = ?", (user_id,)
    ).fetchone()["c"]
    exists = conn.execute(
        "SELECT 1 FROM user_skills WHERE user_id = ? AND skill = ? AND kind = ?",
        (user_id, skill, kind),
    ).fetchone()
    if not exists and count >= MAX_SKILLS_PER_USER:
        raise ProfileError(f"at most {MAX_SKILLS_PER_USER} skills per user")

    conn.execute(
        "INSERT INTO user_skills (user_id, skill, kind, price) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id, skill, kind) DO UPDATE SET price = excluded.price",
        (user_id, skill, kind, price),
    )


def remove_skill(conn, user_id: str, skill: str, kind: str) -> bool:
    cur = conn.execute(
        "DELETE FROM user_skills WHERE user_id = ? AND skill = ? AND kind = ?",
        (user_id, normalize_skill(skill), kind),
    )
    return cur.rowcount > 0


# ----------------------------------------------------------------- search

def find_teachers(conn, skill: str, city: str | None = None, limit: int = 20) -> list[dict]:
    """Teachers of a skill, cheapest first. Pass city to filter (case-insensitive)."""
    skill = normalize_skill(skill)
    sql = (
        "SELECT p.user_id, p.name, p.city, p.bio, s.price "
        "FROM user_skills s JOIN profiles p ON p.user_id = s.user_id "
        "WHERE s.kind = 'teach' AND s.skill = ?"
    )
    params: list = [skill]
    if city and city.strip():
        sql += " AND p.city_key = ?"
        params.append(city_key(city))
    sql += " ORDER BY s.price ASC, p.name ASC LIMIT ?"
    params.append(max(1, min(limit, 100)))
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def suggest_skills(conn, prefix: str, limit: int = 10) -> list[str]:
    """Autocomplete for the search box: most popular teachable skills starting with prefix."""
    prefix = re.sub(r"\s+", " ", prefix.strip().lower())
    if not prefix:
        return []
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = conn.execute(
        "SELECT skill, COUNT(*) AS n FROM user_skills "
        "WHERE kind = 'teach' AND skill LIKE ? ESCAPE '\\' "
        "GROUP BY skill ORDER BY n DESC, skill ASC LIMIT ?",
        (escaped + "%", max(1, min(limit, 20))),
    ).fetchall()
    return [r["skill"] for r in rows]


def find_matches(conn, user_id: str, limit: int = 20) -> list[dict]:
    """Teachers for what THIS user wants to learn (their 'learn' list), cheapest first."""
    rows = conn.execute(
        "SELECT p.user_id, p.name, p.city, t.skill, t.price "
        "FROM user_skills l "
        "JOIN user_skills t ON t.skill = l.skill AND t.kind = 'teach' "
        "JOIN profiles p ON p.user_id = t.user_id "
        "WHERE l.user_id = ? AND l.kind = 'learn' AND t.user_id != ? "
        "ORDER BY t.price ASC, p.name ASC LIMIT ?",
        (user_id, user_id, max(1, min(limit, 100))),
    ).fetchall()
    return [dict(r) for r in rows]


def find_swap_matches(conn, user_id: str, limit: int = 20) -> list[dict]:
    """Best people to swap with, mutual swaps first.

    For every other user we look at two things:
      they_teach - skills they teach that I want to learn (I would pay them credits)
      i_teach    - skills I teach that they want to learn (they would pay me credits)
    mutual = both lists are non-empty: a real swap, no credits needed.
    Order: mutual swaps first, then more matching skills, then name.
    """
    uid = user_id
    they_teach_rows = conn.execute(
        "SELECT t.user_id AS other, t.skill, t.price "
        "FROM user_skills l JOIN user_skills t ON t.skill = l.skill AND t.kind = 'teach' "
        "WHERE l.user_id = ? AND l.kind = 'learn' AND t.user_id != ?",
        (uid, uid),
    ).fetchall()
    i_teach_rows = conn.execute(
        "SELECT l.user_id AS other, l.skill "
        "FROM user_skills m JOIN user_skills l ON l.skill = m.skill AND l.kind = 'learn' "
        "WHERE m.user_id = ? AND m.kind = 'teach' AND l.user_id != ?",
        (uid, uid),
    ).fetchall()

    people: dict[str, dict] = {}
    for r in they_teach_rows:
        p = people.setdefault(r["other"], {"they_teach": [], "i_teach": []})
        p["they_teach"].append({"skill": r["skill"], "price": r["price"]})
    for r in i_teach_rows:
        p = people.setdefault(r["other"], {"they_teach": [], "i_teach": []})
        p["i_teach"].append(r["skill"])
    if not people:
        return []

    marks = ",".join("?" * len(people))
    info = {
        r["user_id"]: r
        for r in conn.execute(
            f"SELECT user_id, name, city FROM profiles WHERE user_id IN ({marks})",
            list(people),
        ).fetchall()
    }
    result = []
    for other, p in people.items():
        if other not in info:  # skills without a profile: skip
            continue
        p["they_teach"].sort(key=lambda s: s["skill"])
        p["i_teach"].sort()
        result.append({
            "user_id": other,
            "name": info[other]["name"],
            "city": info[other]["city"],
            "mutual": bool(p["they_teach"] and p["i_teach"]),
            "they_teach": p["they_teach"],
            "i_teach": p["i_teach"],
        })
    result.sort(key=lambda x: (not x["mutual"], -(len(x["they_teach"]) + len(x["i_teach"])), x["name"]))
    return result[: max(1, min(limit, 100))]


def get_price(conn, teacher_id: str, skill: str) -> int | None:
    """Price in credits/hour that the teacher set for this skill, or None if he does not teach it."""
    row = conn.execute(
        "SELECT price FROM user_skills WHERE user_id = ? AND skill = ? AND kind = 'teach'",
        (teacher_id, normalize_skill(skill)),
    ).fetchone()
    return row["price"] if row else None


def get_names(conn, user_ids: list[str]) -> dict[str, str]:
    """{user_id: name} for the ids that have a profile."""
    ids = list(set(user_ids))
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(f"SELECT user_id, name FROM profiles WHERE user_id IN ({marks})", ids).fetchall()
    return {r["user_id"]: r["name"] for r in rows}
