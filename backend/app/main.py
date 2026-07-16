"""FastAPI entrypoint for The Ledger GA4 reporting backend."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import scheduler
from .config import settings
from .routers import ask, connections, export, insights, jobs, profiles, reports

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="The Ledger — GA4 API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(profiles.router)
app.include_router(reports.router)
app.include_router(insights.router)
app.include_router(export.router)
app.include_router(connections.router)
app.include_router(jobs.router)
app.include_router(ask.router)


@app.get("/health")
def health():
    return {"status": "ok"}
