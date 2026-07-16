"""CRUD for scheduled per-site jobs (executed by scheduler.run_due_jobs)."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from .. import jobs as store
from .. import profiles

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
def list_jobs(profileId: str | None = None):
    return {"jobs": store.all_jobs(profileId)}


@router.post("", status_code=201)
def create_job(data: dict = Body(...)):
    if profiles.get((data.get("profileId") or "").strip()) is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    try:
        return store.create(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{job_id}")
def update_job(job_id: str, data: dict = Body(...)):
    try:
        updated = store.update(job_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if updated is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return updated


@router.delete("/{job_id}")
def delete_job(job_id: str):
    if not store.delete(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True}
