"""
pipeline.py — Layer 2: Navigation / Pipeline Orchestrator

NEW FLOW:
1. Read my_history.docx (career history) — source of truth for content
2. Extract text from uploaded PDF — defines the STYLE/STRUCTURE of the output CV
3. LLM generates a NEW tailored CV from history, matching the uploaded PDF's style
4. Validation ensures no fabricated entities

Input: PDF bytes (uploaded by user for style) + job description metadata
Output: Preview payload (no DB write until user Confirm)

Two public functions:
  run_pipeline()         → generates preview payload (stateless, no DB write)
  confirm_application()  → saves to DB and writes output files (on user Confirm)
"""

from tools.db_writer import save_application, init_db
from tools.docx_generator import generate_docx
from tools.validator import validate_outputs, ValidationError
from tools.llm_handler import get_modified_outputs, LLMError
from tools.cv_parser import extract_text_from_pdf, extract_text_from_docx, parse_cv
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

# ─── Configuration ────────────────────────────────────────────────────────────

if os.getenv("VERCEL"):
    TMP_DIR = Path("/tmp") / ".tmp"
    OUTPUT_DIR = Path("/tmp") / "output"
    HISTORY_DOC_PATH = _ROOT / "my_history.docx"
else:
    TMP_DIR = _ROOT / os.getenv("TMP_DIR", "./.tmp").lstrip("./")
    OUTPUT_DIR = _ROOT / os.getenv("OUTPUT_DIR", "./output").lstrip("./")
    HISTORY_DOC_PATH = _ROOT / "my_history.docx"


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
        raise PreflightError(
            "Uploaded PDF is empty or too small. Please upload a valid CV PDF.")

    if not HISTORY_DOC_PATH.exists():
        raise PreflightError(
            f"my_history.docx not found at {HISTORY_DOC_PATH}. "
            "Please create this file with your complete career history."
        )

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

    NEW FLOW:
    1. Read my_history.docx (complete career history)
    2. Extract text from uploaded PDF (defines the CV style/structure)
    3. LLM generates a NEW tailored CV from history, matching the PDF's style
    4. Validate output (no fabricated entities)

    Args:
        pdf_bytes: Raw bytes of the uploaded CV PDF (for style reference).
        job_description: Raw job description text from user.
        job_title: Job title (for metadata + cover letter).
        company: Company name (for metadata + cover letter).

    Returns:
        dict with keys: cv_text, modified_cv_latex, cover_letter_text,
        key_changes_summary, history_text, entity_map, validation

    Raises:
        PreflightError: System not ready (missing API key or bad PDF).
        ValidationError: LLM output failed a validation gate.
        LLMError: API call failed.
    """

    # ── Step 1: Pre-flight Check ──────────────────────────────────
    _preflight_check(pdf_bytes)

    # ── Step 2: Read career history (my_history.docx) ─────────────
    history_bytes = HISTORY_DOC_PATH.read_bytes()
    history_text = extract_text_from_docx(history_bytes)
    (TMP_DIR / "history_extracted.txt").write_text(history_text, encoding="utf-8")

    # ── Step 3: Extract text from uploaded PDF (style reference) ──
    reference_cv_text = extract_text_from_pdf(pdf_bytes)
    (TMP_DIR / "cv_extracted.txt").write_text(reference_cv_text, encoding="utf-8")

    # ── Step 4: Parse history → Entity Map (for validation) ───────
    history_entity_map = parse_cv(history_text)
    _write_tmp("history_entity_map.json", history_entity_map)

    # ── Step 5: LLM Call — Generate New Tailored CV + Cover Letter ─
    output_response = get_modified_outputs(
        history_text=history_text,
        reference_cv_text=reference_cv_text,
        job_description=job_description,
    )
    _write_tmp("llm_call_response.json", output_response)

    modified_cv_latex = output_response.get("modified_cv_latex", "")
    cover_letter_text = output_response.get("cover_letter_text", "")
    key_changes_summary = output_response.get("key_changes_summary", [])

    # Write generated CV to .tmp for inspection
    (TMP_DIR / "generated_cv.tex").write_text(modified_cv_latex, encoding="utf-8")

    # ── Step 6: Validate Outputs (against history as source of truth)
    validation_result = validate_outputs(
        history_text=history_text,
        modified_latex=modified_cv_latex,
        history_entity_map=history_entity_map,
    )

    # ── Step 7: Return Preview Payload ────────────────────────────
    return {
        # Uploaded PDF text (style ref, for display)
        "cv_text": reference_cv_text,
        # Generated LaTeX (for download/compile)
        "modified_cv_latex": modified_cv_latex,
        "cover_letter_text": cover_letter_text,
        "key_changes_summary": key_changes_summary,
        # Career history (for reference)
        "history_text": history_text,
        "entity_map": dict(history_entity_map),
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
) -> tuple[str, str]:
    """
    Persist a confirmed application: write files + save to DB.
    Only called after the user explicitly clicks Confirm in the UI.

    Args:
        pipeline_result: The payload returned by run_pipeline().
        applied_date: Optional ISO8601 date string ("YYYY-MM-DD").

    Returns:
        tuple[str, str]: (The UUID of the saved application record, cover letter path or URL).
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

    # ── Save to DB / Vercel Blob ─────────────────────────────────
    has_vercel_blob = bool(os.getenv("BLOB_READ_WRITE_TOKEN"))
    relative_docx = ""
    if has_vercel_blob:
        try:
            from vercel import blob
            blob_folder = docx_path.parent.name

            # Upload DOCX
            try:
                with open(docx_path, "rb") as f:
                    uploaded_docx = blob.put(
                        path=f"applications/{blob_folder}/cover_letter.docx",
                        body=f,
                        access="public"
                    )
            except Exception:
                with open(docx_path, "rb") as f:
                    uploaded_docx = blob.put(
                        path=f"applications/{blob_folder}/cover_letter.docx",
                        body=f,
                        access="private"
                    )
            relative_docx = uploaded_docx.url

            # Upload CV .tex
            try:
                blob.put(
                    path=f"applications/{blob_folder}/cv.tex",
                    body=modified_cv_latex,
                    access="public"
                )
            except Exception:
                blob.put(
                    path=f"applications/{blob_folder}/cv.tex",
                    body=modified_cv_latex,
                    access="private"
                )
        except Exception as upload_err:
            print(f"Warning: Vercel Blob upload failed: {upload_err}")
            has_vercel_blob = False

    if not has_vercel_blob:
        try:
            relative_docx = str(docx_path.relative_to(_ROOT))
        except ValueError:
            relative_docx = str(docx_path)

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

    return record_id, relative_docx


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
