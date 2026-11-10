"""SWAP server entry point.

Run (from this folder):
    export SWAP_SECRET="<32+ random characters>"
    uvicorn main:app --host 0.0.0.0 --port 8000
"""
from fastapi import FastAPI

import auth
from api import router as credits_router
from api_auth import router as auth_router
from api_profiles import router as profiles_router
from api_swaps import router as swaps_router

auth.get_secret()  # stop at startup if SWAP_SECRET is missing, not on the first login

app = FastAPI(title="SWAP API")
for r in (auth_router, profiles_router, swaps_router, credits_router):
    app.include_router(r)


@app.get("/health")
def health():
    return {"ok": True}
