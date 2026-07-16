"""CRUD for saved site profiles."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from .. import profiles as store

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("")
def list_profiles():
    return {"profiles": store.all_profiles()}


@router.get("/{profile_id}")
def get_profile(profile_id: str):
    profile = store.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.post("", status_code=201)
def create_profile(data: dict = Body(...)):
    try:
        return store.create(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{profile_id}")
def update_profile(profile_id: str, data: dict = Body(...)):
    updated = store.update(profile_id, data)
    if updated is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return updated


@router.delete("/{profile_id}")
def delete_profile(profile_id: str):
    if not store.delete(profile_id):
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"ok": True}
