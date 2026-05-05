"""
generate.py — API Routes: CV Generation

POST /api/generate    → Upload PDF + job info, run pipeline, return preview
POST /api/confirm     → Save confirmed application to DB
POST /api/regenerate  → Stateless re-run with same PDF + job info
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from typing import Optional
from pydantic import BaseModel

from navigation.pipeline import run_pipeline, confirm_application, PreflightError
from tools.validator import ValidationError
from tools.llm_handler import LLMError

router = APIRouter()


# ─── Request Model (Confirm only — uses JSON) ─────────────────────────────────

class ConfirmRequest(BaseModel):
    pipeline_result: dict
    applied_date: Optional[str] = None


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/generate")
async def generate(
    cv_pdf: UploadFile = File(..., description="PDF of your master CV (from Overleaf)"),
    job_description: str = Form(...),
    job_title: str = Form(...),
    company: str = Form(...),
):
    """
    Run the full generation pipeline (stateless).
    Accepts a PDF file upload + job metadata as multipart form data.
    Returns the preview payload for the UI.
    Does NOT write to the DB.
    """
    if not job_description.strip():
        raise HTTPException(status_code=400, detail="Job description cannot be empty.")
    if not job_title.strip():
        raise HTTPException(status_code=400, detail="Job title cannot be empty.")
    if not company.strip():
        raise HTTPException(status_code=400, detail="Company name cannot be empty.")
    if not cv_pdf.filename or not cv_pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a PDF.")

    pdf_bytes = await cv_pdf.read()
    if len(pdf_bytes) < 100:
        raise HTTPException(status_code=400, detail="Uploaded PDF appears to be empty.")

    try:
        result = run_pipeline(
            pdf_bytes=pdf_bytes,
            job_description=job_description,
            job_title=job_title,
            company=company,
        )
        return {"status": "ok", "data": result}

    except PreflightError as e:
        raise HTTPException(status_code=503, detail=f"System not ready: {str(e)}")
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"Validation failed: {str(e)}")
    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.post("/confirm")
async def confirm(req: ConfirmRequest):
    """
    Save a confirmed application to the DB and write output files.
    Only called after user explicitly confirms the preview.
    """
    if not req.pipeline_result:
        raise HTTPException(status_code=400, detail="No pipeline result provided.")

    try:
        record_id = confirm_application(
            pipeline_result=req.pipeline_result,
            applied_date=req.applied_date,
        )
        return {"status": "ok", "application_id": record_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save application: {str(e)}")


@router.post("/regenerate")
async def regenerate(
    cv_pdf: UploadFile = File(...),
    job_description: str = Form(...),
    job_title: str = Form(...),
    company: str = Form(...),
):
    """
    Stateless regeneration — identical contract to /generate.
    No prior pipeline context is accepted.
    """
    return await generate(
        cv_pdf=cv_pdf,
        job_description=job_description,
        job_title=job_title,
        company=company,
    )
