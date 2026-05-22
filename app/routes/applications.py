"""
applications.py — API Routes: Application History

GET  /api/applications                    → List all saved applications
GET  /api/applications/{id}               → Get single application detail
PUT  /api/applications/{id}/status        → Mark as applied
GET  /api/applications/{id}/download      → Download cover letter DOCX
"""

import os
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional

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


@router.get("/applications/{record_id}/download")
async def download_cover_letter(record_id: str):
    """
    Download the cover letter DOCX for a saved application.
    - If cover_letter_path is a Vercel Blob URL → fetches via SDK and streams.
    - If it's a local path → serves the file directly.
    """
    record = get_application(record_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Application {record_id} not found.")

    path = record.get("cover_letter_path") or ""
    if not path:
        raise HTTPException(status_code=404, detail="No cover letter file stored for this application.")

    filename = f"cover_letter_{record.get('company', 'unknown')}_{record.get('job_title', 'role')}.docx"
    filename = filename.replace(" ", "_")
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    # ── Vercel Blob URL ────────────────────────────────────────────
    if path.startswith("http://") or path.startswith("https://"):
        try:
            from vercel import blob
            result = blob.get(path, access="public")
        except Exception:
            try:
                from vercel import blob
                result = blob.get(path, access="private")
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Failed to fetch file from Blob: {e}")
        return StreamingResponse(
            iter([result.content]),
            media_type=mime,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ── Local file ────────────────────────────────────────────────
    # Resolve relative to project root or absolute
    _ROOT = Path(__file__).parent.parent.parent
    local_path = Path(path) if Path(path).is_absolute() else _ROOT / path
    if not local_path.exists():
        raise HTTPException(status_code=404, detail="Cover letter file not found on disk.")

    return FileResponse(
        path=str(local_path),
        media_type=mime,
        filename=filename,
    )
