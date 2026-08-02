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
REQUIRED_EDIT_FIELDS = {"edit_id", "section", "original_text",
                        "proposed_text", "justification", "edit_type"}


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
    history_text: str,
    modified_latex: str,
    history_entity_map: EntityMap,
) -> dict[str, Any]:
    """
    Validate the LLM's generated LaTeX CV against the CAREER HISTORY.

    Args:
        history_text: The plain text from the candidate's career history (my_history.docx).
        modified_latex: The LLM-generated LaTeX CV string.
        history_entity_map: Entity map extracted from the career history.

    Returns:
        dict with keys: entity_check (bool), latex_check (bool),
        timeline_check (bool), warnings (list[str])

    Raises:
        ValidationError: If any critical gate fails.
    """
    warnings = []

    # Gate 2A: Entity Check — no fabricated entities in generated LaTeX
    # (validates against the career history as source of truth)
    _check_entities(history_entity_map, modified_latex, history_text)

    # Gate 2B: LaTeX Structure Check
    _check_latex_structure(modified_latex)

    # Gate 2C: Timeline Check — key dates from history must appear in generated CV.
    # Only checks dates from the history that are role/employment dates
    # (skips education dates and other non-role dates to avoid false positives).
    _check_timeline(history_entity_map["dates"], modified_latex)

    return {
        "entity_check": True,
        "latex_check": True,
        "timeline_check": True,
        "warnings": warnings,
    }


def _check_entities(original_map: EntityMap, modified_latex: str, original_text: str = "") -> None:
    """Gate 2A: Anti-hallucination check.

    Validates that named entities (company names, institutions, etc.)
    in the generated LaTeX CV also appear in the source-of-truth text
    (career history or original CV).

    ENTITY EXTRACTION STRATEGY:
    Instead of regex-hunting for capitalized phrases (which grabs whole
    sentences), we segment the modified text by delimiters that typically
    separate entities:
      - Newlines
      - Bullet markers (-, *, \u2022)
      - LaTeX command boundaries
      - Punctuation between items (, | ; : /)

    Then from each segment, we extract the meaningful proper-noun phrases
    (sequences of 1-4 capitalized words that look like names).

    """

    def _norm(s: str) -> str:
        """Normalize: lowercase, strip everything non-alphanumeric."""
        return re.sub(r"[^a-z0-9]", "", s.lower())

    # Normalized source text for lookup
    source_norm = _norm(original_text) if original_text else ""
    if not source_norm:
        return  # Nothing to validate against

    # Normalized entities from entity map
    original_entity_norms = set()
    for category in ("companies", "roles", "technologies"):
        for ent in original_map.get(category, []):
            original_entity_norms.add(_norm(ent))

    # ── 1. PREPARE TEXT ──
    # Strip LaTeX commands
    text_no_cmds = re.sub(
        r"\\[a-zA-Z]+\*?(\[[^\]]*\])?([{]?)", " ", modified_latex)
    text_no_cmds = re.sub(r"[{}\\]", " ", text_no_cmds)

    # ── 2. SEGMENT TEXT ──
    # Split into lines/segments on common delimiters
    segments = re.split(r"[\n\r;|(),]", text_no_cmds)
    segments = [s.strip() for s in segments if s.strip()]

    # ── 3. EXTRACT CANDIDATES ──
    candidates = set()

    for seg in segments:
        # Skip segment if it's just a number/date or very short
        if len(seg) < 3:
            continue

        # Skip segments that are dates or years
        if re.match(r"^[\d\s\-–—\.]+$", seg):
            continue

        # Clean the segment of remaining punctuation
        seg_clean = re.sub(r"[^a-zA-Z0-9\s.-]", " ", seg)
        seg_clean = re.sub(r"\s+", " ", seg_clean).strip()

        # Break into words
        words = seg_clean.split()
        if not words:
            continue

        # Find sequences of 2-4 capitalized words (proper noun phrases)
        i = 0
        while i < len(words):
            w = words[i]
            # Skip if word is lowercase, number, or common word
            if not w or len(w) < 2:
                i += 1
                continue

            # Check if this word starts with uppercase (could be proper noun)
            if w[0].isupper():
                # Build a phrase starting here (max 4 words)
                phrase_words = [w]
                j = i + 1
                while j < len(words) and j < i + 4:
                    wj = words[j]
                    if not wj or len(wj) < 2:
                        break
                    # Allow: all caps (ACME), title case (Dublin Business),
                    # or first-char-upper (HitoAI)
                    if wj[0].isupper() or wj.isupper():
                        phrase_words.append(wj)
                        j += 1
                    else:
                        break

                if len(phrase_words) >= 2:
                    phrase = " ".join(phrase_words)
                    norm = _norm(phrase)
                    if len(norm) >= 4:
                        candidates.add(norm)

                # Move past this capitalized word
                i = max(j, i + 1)
            else:
                i += 1

        # Also extract PascalCase / camelCase single words
        # (e.g. "HitoAI", "DublinBusinessSchool")
        for w in words:
            if re.match(r"^[A-Z][a-z]+(?:[A-Z][a-z0-9]*)+", w):
                norm = _norm(w)
                if len(norm) >= 4:
                    candidates.add(norm)

    # ── 4. STOP WORDS ──
    stop_words = {
        "documentclass", "begindocument", "enddocument", "textbf", "textit",
        "section", "subsection", "itemize", "enumerate", "item", "cventry",
        "rule", "usepackage", "begin", "end", "textrm", "texttt",
        "ref", "label", "newpage", "vspace", "hspace", "center",
        "includegraphics", "summary", "experience", "education", "skills",
        "projects", "certifications", "awards", "publications", "contact",
        "home", "address", "phone", "email", "linkedin", "github",
        "portfolio", "about", "work", "profile", "objective", "languages",
        "tools", "tech", "other", "references", "hobbies", "interests",
        "volunteer", "achievements", "highlights", "keywords", "software",
        "engineer", "developer", "engineer", "intern", "manager", "analyst",
        "scientist", "designer", "specialist", "consultant", "lead", "head",
        "director", "officer", "coordinator", "researcher", "associate",
        "junior", "senior", "principal", "staff", "fullstack", "backend",
        "frontend", "data", "python", "javascript", "java", "typescript",
        "mysql", "postgresql", "docker", "kubernetes", "aws", "azure",
        "gcp", "linux", "git", "github", "api", "rest", "sql", "html",
        "css", "react", "node", "django", "flask", "fastapi", "pandas",
        "numpy", "tensorflow", "pytorch", "machine", "learning", "deep",
        "artificial", "intelligence", "ml", "ai", "cloud", "devops",
    }

    # ── 5. CHECK EACH CANDIDATE ──
    suspicious = set()
    for cand in candidates:
        if len(cand) < 4:
            continue

        # Skip stop words
        if cand in stop_words:
            continue

        # ALSO skip candidates that are just tech terms
        # (tech terms are common and likely legitimate)
        from tools.cv_parser import TECH_VOCABULARY
        tech_norms = {_norm(t) for t in TECH_VOCABULARY}
        if cand in tech_norms:
            continue

        # 1) Verbatim in source text
        if cand in source_norm:
            continue

        # 2) In original entity list from entity map
        if cand in original_entity_norms:
            continue

        # 3) Word-level overlap: any word (>= 3 chars) in source
        found = False
        # Get individual words from the candidate (they were concatenated)
        # Try to find any 4+ char substring that's in source words
        cand_words = re.findall(r"[a-z]{3,}", cand)
        for w in cand_words:
            if w in source_norm:
                found = True
                break

        # 4) Any 5+ char substring in source text
        #    (lenient enough to catch "hitoai" in "HitoAI Limited"
        #     vs "Hito AI Ltd" while still catching fabrications)
        if not found:
            min_len = min(5, len(cand))
            for i in range(len(cand) - min_len + 1):
                if cand[i:i + min_len] in source_norm:
                    found = True
                    break

        # 5) Overlap with original entities
        #    More lenient: check for SHORT shared substrings (5+ chars)
        #    This accepts variations like "Hito AI Ltd" vs "HitoAI Limited"
        #    (shared "hitoai") while still catching fabrications.
        if not found:
            for orig in original_entity_norms:
                if not orig or len(orig) < 4:
                    continue
                # Direct containment either way
                if cand in orig or orig in cand:
                    found = True
                    break
                # Check for 5+ char shared substring
                # Find longest common substring between cand and orig
                for sub_len in range(min(len(cand), len(orig)), 4, -1):
                    # Check all substrings of this length
                    found_shared = False
                    for i in range(len(cand) - sub_len + 1):
                        sub = cand[i:i + sub_len]
                        if sub in orig:
                            found_shared = True
                            break
                    if found_shared:
                        found = True
                        break
                if found:
                    break

        # 6) If no overlap at all → suspicious
        if not found:
            suspicious.add(cand)

    if suspicious:
        raise ValidationError(
            f"Potential hallucination detected: {suspicious}. "
            f"These entities appear in the generated CV but have no overlap with the source text."
        )


def _check_latex_structure(modified_latex: str) -> None:
    """Gate 2B: Validate LaTeX structural integrity of the generated CV."""
    if r"\begin{document}" not in modified_latex:
        raise ValidationError(
            "LaTeX structure invalid: \\begin{document} is missing.")
    if r"\end{document}" not in modified_latex:
        raise ValidationError(
            "LaTeX structure invalid: \\end{document} is missing.")

    begin_pos = modified_latex.index(r"\begin{document}")
    end_pos = modified_latex.index(r"\end{document}")
    if begin_pos >= end_pos:
        raise ValidationError(
            "LaTeX structure invalid: \\end{document} appears before \\begin{document}.")

    # Check balanced curly braces
    brace_count = 0
    for char in modified_latex:
        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
        if brace_count < 0:
            raise ValidationError(
                "LaTeX structure invalid: unmatched closing brace '}' found.")
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
    """Gate 2C: Verify timeline dates from history appear in the generated CV.

    This is LENIENT because the CV may legitimately omit older/irrelevant
    positions. We only verify that KEY employment dates appear.

    Strategy:
    - Look for ranges like "2019-2023" or "May 2022 - Present" in generated CV.
    - Only flag if the generated CV contains DATES that don't appear in the
      history at all (i.e. fabricated dates).
    - Don't flag missing dates (CV can omit content).
    """
    # Normalize en-dashes, em-dashes, and multiple hyphens to a single hyphen
    def _norm(text: str) -> str:
        text = re.sub(r"\s+", " ", text).strip()
        text = text.replace("–", "-").replace("—", "-")  # en-dash, em-dash
        text = re.sub(r"-{2,}", "-", text)  # -- → -
        text = re.sub(r"(\d)\s*-\s*(\d)", r"\1-\2",
                      text)  # 2024 - 2025 → 2024-2025
        return text

    # Normalize the history dates for reference
    history_dates_norm = {_norm(d) for d in original_dates if d}

    # Extract all date-like patterns from the generated CV
    generated_dates = set()
    date_patterns = [
        r"\b\d{4}\s*[-–—]+\s*(?:present|current|now|ongoing)\b",
        r"\b\d{4}\s*[-–—]+\s*\d{4}\b",
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b",
    ]
    for pattern in date_patterns:
        for match in re.finditer(pattern, modified_latex, re.IGNORECASE):
            generated_dates.add(_norm(match.group(0)))

    # Find dates in generated CV that are NOT in history dates
    # (but only if the date is substantial - year ranges, not single years)
    suspicious = set()
    for date in generated_dates:
        # Skip single years (they might just be project years or education)
        if re.match(r"^\d{4}$", date):
            continue
        # Skip "- Present" style dates that don't have a start year
        if date not in history_dates_norm:
            # Check if the START YEAR of this range exists in history
            start_year = re.search(r"(\d{4})", date)
            if start_year and any(start_year.group(1) in hd for hd in history_dates_norm):
                continue  # The year appears in history - likely legitimate variation
            suspicious.add(date)

    if suspicious:
        raise ValidationError(
            f"Timeline check failed: the following dates in the generated CV "
            f"do not appear in the career history: {suspicious}"
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
        result = validate_outputs(
            sample_original, sample_modified_ok, entity_map)
        print(
            f"✅ PASS | Entity: {result['entity_check']} | "
            f"LaTeX: {result['latex_check']} | Timeline: {result['timeline_check']} | "
            f"Warnings: {result['warnings']}")
    except ValidationError as e:
        print(f"❌ FAIL: {e}")

    print("\n--- Test 2: Hallucinated company (should FAIL) ---")
    try:
        result = validate_outputs(
            sample_original, sample_modified_bad, entity_map)
        print(f"❌ Should have failed! Result: {result}")
    except ValidationError as e:
        print(f"✅ Correctly rejected: {e}")
