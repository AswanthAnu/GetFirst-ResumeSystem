"""
validator.py — Layer 3 Tool: Anti-Hallucination Validation Gates

All validation is deterministic — no LLM involved.
Implements two checkpoints:
  - Checkpoint 1: Edit Plan Validation (after LLM Call 1)
  - Checkpoint 2: Output Validation (after LLM Call 2)
"""

import re
from typing import Any
from tools.cv_parser import parse_cv, EntityMap


# ─── Custom Exception ─────────────────────────────────────────────────────────

class ValidationError(Exception):
    """Raised when a validation gate rejects the LLM output."""
    pass


# ─── Checkpoint 1: Edit Plan Validation ──────────────────────────────────────

ALLOWED_EDIT_TYPES = {"rephrase", "emphasize", "reorder", "trim"}
REQUIRED_EDIT_FIELDS = {"edit_id", "section", "original_text", "proposed_text", "justification", "edit_type"}


def validate_edit_plan(edit_plan: dict, max_edits: int = 10) -> None:
    """
    Validate the LLM's edit plan before applying it.

    Args:
        edit_plan: Parsed dict from LLM Call 1 response.
        max_edits: Maximum allowed edits (from .env MAX_EDITS).

    Raises:
        ValidationError: If any gate fails.
    """
    edits = edit_plan.get("edit_plan", [])
    total = edit_plan.get("total_edits", len(edits))

    # Gate 1A: Edit Count Check
    if total > max_edits:
        raise ValidationError(
            f"Edit plan has {total} edits. Maximum allowed is {max_edits}. "
            f"Please regenerate."
        )

    for i, edit in enumerate(edits):
        edit_id = edit.get("edit_id", i)

        # Gate 1B: Schema Completeness Check
        missing_fields = REQUIRED_EDIT_FIELDS - set(edit.keys())
        if missing_fields:
            raise ValidationError(
                f"Edit #{edit_id} is missing required fields: {missing_fields}"
            )

        # Gate 1C: Edit Type Check
        edit_type = edit.get("edit_type", "").strip().lower()
        if edit_type not in ALLOWED_EDIT_TYPES:
            raise ValidationError(
                f"Edit #{edit_id} has invalid edit_type: '{edit_type}'. "
                f"Allowed types: {ALLOWED_EDIT_TYPES}"
            )

        # Gate 1D: Non-empty justification
        if not edit.get("justification", "").strip():
            raise ValidationError(
                f"Edit #{edit_id} has an empty justification. All edits must be justified."
            )


# ─── Checkpoint 2: Output Validation ─────────────────────────────────────────

def validate_outputs(
    original_text: str,
    modified_latex: str,
    original_entity_map: EntityMap,
) -> dict[str, Any]:
    """
    Validate the LLM's generated LaTeX CV.

    Args:
        original_text: The plain text extracted from the uploaded PDF CV.
        modified_latex: The LLM-generated LaTeX CV string.
        original_entity_map: Entity map extracted from the original PDF text.

    Returns:
        dict with keys: entity_check (bool), latex_check (bool),
        timeline_check (bool), warnings (list[str])

    Raises:
        ValidationError: If any critical gate fails.
    """
    warnings = []

    # Gate 2A: Entity Check — no new entities in generated LaTeX
    _check_entities(original_entity_map, modified_latex, original_text)

    # Gate 2B: LaTeX Structure Check
    _check_latex_structure(modified_latex)

    # Gate 2C: Timeline Preservation Check — dates from PDF must appear in generated LaTeX
    _check_timeline(original_entity_map["dates"], modified_latex)

    return {
        "entity_check": True,
        "latex_check": True,
        "timeline_check": True,
        "warnings": warnings,
    }


def _check_entities(original_map: EntityMap, modified_latex: str, original_text: str = "") -> None:
    """Gate 2A: Reject if modified CV contains entities not in the original."""
    modified_map = parse_cv(modified_latex)

    categories = ["companies", "roles", "technologies"]
    for category in categories:
        original_set = {e.lower() for e in original_map.get(category, [])}
        modified_set = {e.lower() for e in modified_map.get(category, [])}
        new_entities = modified_set - original_set

        # Filter out false positives: entities that exist verbatim in the
        # original text but were missed by the parser (e.g. due to PDF
        # space-merging like "RESTAPIs" vs "REST APIs").
        if new_entities and original_text:
            false_positives = set()
            text_lower = original_text.lower()
            for entity in new_entities:
                if entity in text_lower:
                    false_positives.add(entity)
            new_entities -= false_positives

        if new_entities:
            raise ValidationError(
                f"Hallucination detected in '{category}': "
                f"new entities found that were not in original CV: {new_entities}"
            )


def _check_latex_structure(modified_latex: str) -> None:
    """Gate 2B: Validate LaTeX structural integrity of the generated CV."""
    if r"\begin{document}" not in modified_latex:
        raise ValidationError("LaTeX structure invalid: \\begin{document} is missing.")
    if r"\end{document}" not in modified_latex:
        raise ValidationError("LaTeX structure invalid: \\end{document} is missing.")

    begin_pos = modified_latex.index(r"\begin{document}")
    end_pos = modified_latex.index(r"\end{document}")
    if begin_pos >= end_pos:
        raise ValidationError("LaTeX structure invalid: \\end{document} appears before \\begin{document}.")

    # Check balanced curly braces
    brace_count = 0
    for char in modified_latex:
        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
        if brace_count < 0:
            raise ValidationError("LaTeX structure invalid: unmatched closing brace '}' found.")
    if brace_count != 0:
        raise ValidationError(
            f"LaTeX structure invalid: {brace_count} unclosed brace(s) '{{' detected."
        )

    # Check balanced \begin{} / \end{} environments
    begins = re.findall(r"\\begin\{([^}]+)\}", modified_latex)
    ends = re.findall(r"\\end\{([^}]+)\}", modified_latex)
    if len(begins) != len(ends):
        raise ValidationError(
            f"LaTeX structure invalid: {len(begins)} \\begin{{}} vs {len(ends)} \\end{{}} — mismatched."
        )


def _check_timeline(original_dates: list[str], modified_latex: str) -> None:
    """Gate 2C: Verify all original dates are preserved in the modified CV."""
    # Normalize en-dashes, em-dashes, and multiple hyphens to a single hyphen
    def _norm(text: str) -> str:
        text = re.sub(r"\s+", " ", text).strip()
        text = text.replace("–", "-").replace("—", "-")  # en-dash, em-dash
        text = re.sub(r"-{2,}", "-", text)  # -- → -
        text = re.sub(r"(\d)\s*-\s*(\d)", r"\1-\2", text)  # 2024 - 2025 → 2024-2025
        return text

    normalized_latex = _norm(modified_latex)
    missing = []
    for date in original_dates:
        date_clean = _norm(date)
        if date_clean not in normalized_latex:
            missing.append(date_clean)

    if missing:
        raise ValidationError(
            f"Timeline check failed: the following dates from the original CV "
            f"are missing in the modified CV: {missing}"
        )



# ─── CLI Test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Validator — self-test with a simple LaTeX pair")

    sample_original = r"""
\documentclass{article}
\begin{document}
\section{Experience}
\cventry{2019--2023}{Software Engineer}{Acme Corp}{Dublin}{}{}
Developed Python microservices and REST APIs.
\section{Skills}
Python, Docker, AWS
\end{document}
"""

    sample_modified_ok = sample_original.replace(
        "Developed Python microservices and REST APIs.",
        "Built and maintained Python microservices and REST APIs at scale."
    )

    sample_modified_bad = sample_original.replace(
        "Acme Corp", "NEW FAKE COMPANY"
    )

    from tools.cv_parser import parse_cv
    entity_map = parse_cv(sample_original)

    print("\n--- Test 1: Valid modification (should PASS) ---")
    try:
        result = validate_outputs(sample_original, sample_modified_ok, entity_map)
        print(f"✅ PASS | Scope: {result['scope_percent']:.1f}% | Warnings: {result['warnings']}")
    except ValidationError as e:
        print(f"❌ FAIL: {e}")

    print("\n--- Test 2: Hallucinated company (should FAIL) ---")
    try:
        result = validate_outputs(sample_original, sample_modified_bad, entity_map)
        print(f"❌ Should have failed! Result: {result}")
    except ValidationError as e:
        print(f"✅ Correctly rejected: {e}")
