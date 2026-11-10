"""FastAPI router for SWAP profiles, skills and teacher search.

NOT RUN YET: fastapi is not installed in my workspace, so this file is only
syntax-checked. The logic it calls (profiles.py) is tested.

Connect it next to the credits router:
    from api_profiles import router as profiles_router
    app.include_router(profiles_router)

Reuses get_conn / current_user_id from api.py (replace the placeholder auth there!).
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import profiles
from api import current_user_id, get_conn

router = APIRouter(tags=["profiles"])


def _init(conn=Depends(get_conn)):
    profiles.init_schema(conn)  # cheap: CREATE TABLE IF NOT EXISTS
    return conn


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    city: str = Field(default="", max_length=60)
    bio: str = Field(default="", max_length=500)


class SkillIn(BaseModel):
    skill: str = Field(min_length=1, max_length=50)
    kind: Literal["teach", "learn"]
    price: int | None = Field(default=None, ge=1, le=100)


def _http(e: Exception) -> HTTPException:
    if isinstance(e, profiles.ProfileNotFound):
        return HTTPException(404, str(e))
    if isinstance(e, ValueError):
        return HTTPException(422, str(e))
    return HTTPException(409, str(e))


@router.put("/profile")
def save_profile(body: ProfileIn, user_id: str = Depends(current_user_id), conn=Depends(_init)):
    try:
        return profiles.save_profile(conn, user_id, body.name, body.city, body.bio)
    except (profiles.ProfileError, ValueError) as e:
        raise _http(e)


@router.get("/profile/{target_id}")
def get_profile(target_id: str, conn=Depends(_init)):
    try:
        return profiles.get_profile(conn, target_id)
    except profiles.ProfileError as e:
        raise _http(e)


@router.post("/skills", status_code=204)
def add_skill(body: SkillIn, user_id: str = Depends(current_user_id), conn=Depends(_init)):
    try:
        profiles.add_skill(conn, user_id, body.skill, body.kind, body.price)
    except (profiles.ProfileError, ValueError) as e:
        raise _http(e)


@router.delete("/skills", status_code=204)
def remove_skill(skill: str, kind: Literal["teach", "learn"],
                 user_id: str = Depends(current_user_id), conn=Depends(_init)):
    try:
        if not profiles.remove_skill(conn, user_id, skill, kind):
            raise HTTPException(404, "skill not found")
    except ValueError as e:
        raise _http(e)


@router.get("/search/teachers")
def search_teachers(skill: str, city: str | None = None, limit: int = 20, conn=Depends(_init)):
    try:
        return profiles.find_teachers(conn, skill, city, limit)
    except ValueError as e:
        raise _http(e)


@router.get("/search/suggest")
def suggest(q: str, conn=Depends(_init)):
    return profiles.suggest_skills(conn, q)


@router.get("/matches")
def matches(limit: int = 20, user_id: str = Depends(current_user_id), conn=Depends(_init)):
    """People to swap with. mutual=true means a real swap (each teaches what the other wants)."""
    return profiles.find_swap_matches(conn, user_id, limit)
