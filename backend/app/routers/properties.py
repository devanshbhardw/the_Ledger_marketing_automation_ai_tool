"""List the GA4 properties the service account can access."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from google.api_core.exceptions import GoogleAPIError

from .. import ga4

router = APIRouter(prefix="/properties", tags=["properties"])


@router.get("")
def get_properties():
    try:
        return {"properties": ga4.list_properties()}
    except GoogleAPIError as exc:
        raise HTTPException(status_code=502, detail=f"GA4 Admin API error: {exc}")
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
