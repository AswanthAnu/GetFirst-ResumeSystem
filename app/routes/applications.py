"""
applications.py — API Routes: Application History

GET  /api/applications        → List all saved applications
GET  /api/applications/{id}   → Get single application detail
PUT  /api/applications/{id}/status → Mark as applied
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from tools.db_writer import get_all_applications, get_application, update_status

router = APIRouter()


class StatusUpdate(BaseModel):
    status: str  # "confirmed" | "applied"


@router.get("/applications")
async def list_applications():
    """Return all saved applications (without full CV LaTeX)."""
    try:
        records = get_all_applications()
        return {"status": "ok", "data": records}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/applications/{record_id}")
async def get_application_detail(record_id: str):
    """Return full application record including CV LaTeX."""
    record = get_application(record_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Application {record_id} not found.")
    return {"status": "ok", "data": record}


@router.put("/applications/{record_id}/status")
async def update_application_status(record_id: str, body: StatusUpdate):
    """Update the status of an application (e.g., mark as 'applied')."""
    try:
        success = update_status(record_id, body.status)
        if not success:
            raise HTTPException(status_code=404, detail=f"Application {record_id} not found.")
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
