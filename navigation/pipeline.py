"""
pipeline.py — Layer 2: Navigation / Pipeline Orchestrator

Routes data between tools in strict order per cv_pipeline.md SOP.
Does NOT perform heavy processing — it delegates entirely to Layer 3 tools.

Input: PDF bytes (uploaded by user) + job description metadata
Output: Preview payload (no DB write until user Confirm)

Two public functions:
  run_pipeline()         → generates preview payload (stateless, no DB write)
  confirm_application()  → saves to DB and writes output files (on user Confirm)
"""

import os
import json
import shutil
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load .env from project root
_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env")

# Layer 3 imports
from tools.cv_parser import extract_text_from_pdf, parse_cv
from tools.llm_handler import get_edit_plan, get_modified_outputs, LLMError
from tools.validator import validate_edit_plan, validate_outputs, ValidationError
from tools.docx_generator import generate_docx
from tools.db_writer import save_application, init_db

# ─── Configuration ────────────────────────────────────────────────────────────

if os.getenv("VERCEL"):
    TMP_DIR = Path("/tmp") / ".tmp"
    OUTPUT_DIR = Path("/tmp") / "output"
else:
    TMP_DIR = _ROOT / os.getenv("TMP_DIR", "./.tmp").lstrip("./")
    OUTPUT_DIR = _ROOT / os.getenv("OUTPUT_DIR", "./output").lstrip("./")
MAX_EDITS = int(os.getenv("MAX_EDITS", "10"))


# ─── Pre-flight Check ─────────────────────────────────────────────────────────

class PreflightError(Exception):
    """Raised when the system cannot proceed due to a configuration issue."""
    pass


def _preflight_check(pdf_bytes: bytes) -> None:
    """
    Step 1: Verify the system is ready.
    Raises PreflightError on any failure.
    """
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key or api_key == "your_api_key_here":
        raise PreflightError(
            "DEEPSEEK_API_KEY is not set in .env. "
            "Add your DeepSeek API key to proceed."
        )

    if not pdf_bytes or len(pdf_bytes) < 100:
        raise PreflightError("Uploaded PDF is empty or too small. Please upload a valid CV PDF.")

    # Clear .tmp directory for this run
    if TMP_DIR.exists():
        shutil.rmtree(TMP_DIR)
    TMP_DIR.mkdir(parents=True, exist_ok=True)


# ─── Main Pipeline ────────────────────────────────────────────────────────────

def run_pipeline(
    pdf_bytes: bytes,
    job_description: str,
    job_title: str,
    company: str,
) -> dict:
    """
    Execute the full generation pipeline (stateless).
    Does NOT write to the DB or output/ folder.
    Returns a preview payload for the UI to display.

    Args:
        pdf_bytes: Raw bytes of the uploaded CV PDF.
        job_description: Raw job description text from user.
        job_title: Job title (for metadata + cover letter).
        company: Company name (for metadata + cover letter).

    Returns:
        dict with keys: cv_text, modified_cv_latex, cover_letter_text,
        key_changes_summary, analysis, edit_plan, entity_map, validation

    Raises:
        PreflightError: System not ready (missing API key or bad PDF).
        ValidationError: LLM output failed a validation gate.
        LLMError: API call failed.
    """

    # ── Step 1: Pre-flight Check ──────────────────────────────────
    _preflight_check(pdf_bytes)

    # ── Step 2: Extract text from PDF ────────────────────────────
    cv_text = extract_text_from_pdf(pdf_bytes)
    (TMP_DIR / "cv_extracted.txt").write_text(cv_text, encoding="utf-8")

    # ── Step 3: Parse CV → Entity Map ────────────────────────────
    entity_map = parse_cv(cv_text)
    _write_tmp("entity_map.json", entity_map)

    # ── Step 4: LLM Call 1 — Analysis + Edit Plan ────────────────
    edit_plan_response = get_edit_plan(
        cv_text=cv_text,
        job_description=job_description,
        entity_map=entity_map,
        max_edits=MAX_EDITS,
    )
    _write_tmp("llm_call1_response.json", edit_plan_response)

    # ── Step 5: Validate Edit Plan ────────────────────────────────
    validate_edit_plan(edit_plan_response, max_edits=MAX_EDITS)

    # ── Step 6: LLM Call 2 — Generate LaTeX CV + Cover Letter ────
    output_response = get_modified_outputs(
        cv_text=cv_text,
        edit_plan=edit_plan_response,
        job_description=job_description,
    )
    _write_tmp("llm_call2_response.json", output_response)

    modified_cv_latex = output_response.get("modified_cv_latex", "")
    cover_letter_text = output_response.get("cover_letter_text", "")
    key_changes_summary = output_response.get("key_changes_summary", [])

    # Write generated CV to .tmp for inspection
    (TMP_DIR / "generated_cv.tex").write_text(modified_cv_latex, encoding="utf-8")

    # ── Step 7: Validate Outputs ──────────────────────────────────
    validation_result = validate_outputs(
        original_text=cv_text,
        modified_latex=modified_cv_latex,
        original_entity_map=entity_map,
    )

    # ── Step 8: Return Preview Payload ────────────────────────────
    return {
        "cv_text": cv_text,                          # Original plain text (for display)
        "modified_cv_latex": modified_cv_latex,       # Generated LaTeX (for download/compile)
        "cover_letter_text": cover_letter_text,
        "key_changes_summary": key_changes_summary,
        "analysis": edit_plan_response.get("analysis", {}),
        "edit_plan": edit_plan_response.get("edit_plan", []),
        "entity_map": dict(entity_map),
        "validation": validation_result,
        "meta": {
            "job_title": job_title,
            "company": company,
            "job_description": job_description,
        }
    }


# ─── Confirm & Save ───────────────────────────────────────────────────────────

def confirm_application(
    pipeline_result: dict,
    applied_date: Optional[str] = None,
) -> str:
    """
    Persist a confirmed application: write files + save to DB.
    Only called after the user explicitly clicks Confirm in the UI.

    Args:
        pipeline_result: The payload returned by run_pipeline().
        applied_date: Optional ISO8601 date string ("YYYY-MM-DD").

    Returns:
        The UUID of the saved application record.
    """
    init_db()

    meta = pipeline_result["meta"]
    job_title = meta["job_title"]
    company = meta["company"]
    job_description = meta["job_description"]
    modified_cv_latex = pipeline_result["modified_cv_latex"]
    cover_letter_text = pipeline_result["cover_letter_text"]
    key_changes_summary = pipeline_result["key_changes_summary"]

    # ── Generate DOCX Cover Letter ───────────────────────────────
    docx_path = generate_docx(
        cover_letter_text=cover_letter_text,
        job_title=job_title,
        company=company,
        output_dir=OUTPUT_DIR,
    )

    # ── Save CV .tex to same output folder ───────────────────────
    cv_output_path = docx_path.parent / "cv.tex"
    cv_output_path.write_text(modified_cv_latex, encoding="utf-8")

    # ── Save to DB ───────────────────────────────────────────────
    relative_docx = str(docx_path.relative_to(_ROOT))
    record_id = save_application(
        job_title=job_title,
        company=company,
        job_description_raw=job_description,
        cv_text_original=pipeline_result["cv_text"],
        cv_latex_generated=modified_cv_latex,
        cover_letter_path=relative_docx,
        key_changes_summary=key_changes_summary,
        applied_date=applied_date,
    )

    return record_id


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _write_tmp(filename: str, data: dict | list) -> None:
    """Write intermediate JSON data to .tmp/ for debugging."""
    try:
        (TMP_DIR / filename).write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8"
        )
    except Exception:
        pass  # Non-critical
