"""
llm_handler.py — Layer 3 Tool: Structured DeepSeek API Calls

Handles both LLM pipeline calls with strict prompt templates and JSON mode.
All prompt logic lives here — no ad-hoc prompt strings elsewhere in the codebase.

Call 1: get_edit_plan()      → Analysis + Edit Plan
Call 2: get_modified_outputs() → Modified CV LaTeX + Cover Letter
"""

import os
import json
import requests
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MAX_EDITS = int(os.getenv("MAX_EDITS", "10"))

# Reasoning models (deepseek-v4-pro, deepseek-reasoner, etc.) do not support
# response_format json_object. They also need explicit instruction to output
# raw JSON since they natively produce reasoning_content.
_IS_REASONING_MODEL = "reasoner" in MODEL.lower() or "v4-pro" in MODEL.lower() or "r1" in MODEL.lower()


# ─── JSON Schemas (as strings, injected into prompts) ─────────────────────────

EDIT_PLAN_SCHEMA = """{
  "analysis": {
    "key_requirements": ["string"],
    "matching_skills": ["string"],
    "gaps": ["string"],
    "emphasis_targets": ["string"]
  },
  "edit_plan": [
    {
      "edit_id": 1,
      "section": "string — section name from CV",
      "original_text": "string — exact text from CV to change",
      "proposed_text": "string — replacement text",
      "justification": "string — why this change aligns with the job",
      "edit_type": "rephrase | emphasize | reorder | trim"
    }
  ],
  "total_edits": 0
}"""

OUTPUT_SCHEMA = """{
  "modified_cv_latex": "string — complete modified LaTeX document",
  "cover_letter_text": "string — plain text cover letter (no LaTeX formatting)",
  "key_changes_summary": ["string — max 10 concise change descriptions"]
}"""


# ─── Prompt Templates ─────────────────────────────────────────────────────────

SYSTEM_PROMPT_CALL_1 = """You are a professional CV optimization specialist with deep expertise in ATS systems and technical recruiting.

Your task is to analyze a job description and a candidate's CV (provided as plain text extracted from a PDF), then produce a precise analysis and edit plan.

CRITICAL RULES — YOU MUST FOLLOW THESE EXACTLY:
1. DO NOT add any new companies, employers, or organizations not already in the CV.
2. DO NOT add any new job titles or roles not already in the CV.
3. DO NOT add any new technologies, tools, or skills not already in the CV.
4. DO NOT add new work experience, projects, achievements, or responsibilities.
5. DO NOT change any dates, timelines, or durations.
6. You may ONLY: rephrase existing text, emphasize existing skills, reorder existing content, or trim existing content.
7. Your edit_plan must contain AT MOST {max_edits} edits total. Set total_edits accordingly.
8. Every single edit MUST include a non-empty justification explaining why it helps.
9. "original_text" must be the exact verbatim text from the CV (it will be used for string matching).

The entity map below is the GROUND TRUTH of what exists in the CV.
Any entity NOT in this list is FORBIDDEN from appearing in your edit plan.

ENTITY MAP (Ground Truth):
Companies: {companies}
Roles: {roles}
Technologies: {technologies}

Return ONLY valid JSON matching this exact schema — no explanation, no preamble, no markdown:
{schema}"""

USER_PROMPT_CALL_1 = """JOB DESCRIPTION:
---
{job_description}
---

CANDIDATE CV (plain text, extracted from PDF):
---
{cv_text}
---

Produce your analysis and edit plan now. Maximum {max_edits} edits. Only use entities from the entity map."""

# ──────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT_CALL_2 = """You are a professional LaTeX CV writer and editor.

You will receive:
1. The candidate's original CV as plain text (extracted from a PDF compiled by Overleaf)
2. An approved edit plan specifying exactly what to change
3. A job description (for the cover letter only)
4. A LaTeX TEMPLATE that defines the exact layout, style, and section structure to use

Your tasks:
A) Generate a complete LaTeX CV by filling the TEMPLATE with content from the CV + exactly the edits in the edit plan.
B) Write a professional plain-text cover letter for the job.

CRITICAL RULES:
1. Apply ONLY the edits listed in the edit plan. No additional changes beyond what is specified.
2. Use the EXACT preamble, style, packages, and section structure from the TEMPLATE below.
3. Replace placeholder text in brackets (e.g. [FIRST], [SUMMARY_TEXT]) with actual CV content.
4. Preserve ALL original content exactly — same companies, roles, dates, and technologies.
5. DO NOT add any companies, roles, technologies, or experiences not in the original CV.
6. DO NOT change any dates, timelines, or durations.
7. The LaTeX document must be complete and compilable, matching the TEMPLATE structure.
8. The cover letter must be plain text only — no LaTeX commands, no markdown.
9. The cover letter must reference ONLY experiences and skills present in the original CV.
10. key_changes_summary: provide at most 10 concise bullet-point summaries of what changed.

LATEX TEMPLATE (follow this exact structure, style, and formatting):
---
{template}
---

Return ONLY valid JSON matching this exact schema — no explanation, no preamble, no markdown:
{schema}"""

USER_PROMPT_CALL_2 = """ORIGINAL CV (plain text, from PDF):
---
{cv_text}
---

APPROVED EDIT PLAN:
---
{edit_plan_json}
---

JOB DESCRIPTION (for cover letter only):
---
{job_description}
---

Generate the complete LaTeX CV with edits applied and write the cover letter."""


# ─── API Call Helper ──────────────────────────────────────────────────────────

class LLMError(Exception):
    """Raised when the LLM API call fails or returns malformed output."""
    pass


def _call_api(system_prompt: str, user_prompt: str, temperature: float = 0.3) -> dict[str, Any]:
    """
    Make a single structured API call to DeepSeek and parse the JSON response.

    Returns:
        Parsed JSON dict from the LLM.

    Raises:
        LLMError: If the API call fails or the response is not valid JSON.
    """
    if not API_KEY or API_KEY == "your_api_key_here":
        raise LLMError(
            "DEEPSEEK_API_KEY is not set in .env. "
            "Run tools/test_llm.py to verify your connection."
        )

    payload: dict[str, Any] = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 16384,
    }

    # Reasoning models don't support json_object response_format;
    # they also don't accept temperature. Rely on prompt instructions instead.
    if _IS_REASONING_MODEL:
        payload["temperature"] = 1.0  # Some reasoning APIs require exactly 1.0
    else:
        payload["response_format"] = {"type": "json_object"}
        payload["temperature"] = temperature

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            f"{BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        raise LLMError("LLM API request timed out after 120 seconds.")
    except requests.exceptions.ConnectionError:
        raise LLMError("LLM API connection failed. Check your internet connection.")
    except requests.exceptions.HTTPError as e:
        raise LLMError(f"LLM API HTTP error {e.response.status_code}: {e.response.text[:500]}")

    data = response.json()
    message = data["choices"][0]["message"]
    content = message.get("content") or ""

    # Reasoning models may put the answer in reasoning_content if content is empty
    if not content:
        content = message.get("reasoning_content") or ""

    if not content:
        raise LLMError(
            f"LLM returned empty content. "
            f"finish_reason: {data['choices'][0].get('finish_reason')}. "
            f"Try increasing max_tokens."
        )

    # Reasoning models without json_object may wrap output in ```json fences
    content = content.strip()
    if content.startswith("```"):
        # Remove opening fence (```json or ```)
        content = re.sub(r"^```(?:json)?\s*\n?", "", content)
        # Remove closing fence
        content = re.sub(r"\n?```\s*$", "", content)

    # Reasoning models may include reasoning text before the JSON object.
    # Extract the outermost JSON object/array.
    json_start = content.find("{")
    json_end = content.rfind("}")
    if json_start != -1 and json_end != -1 and json_end > json_start:
        content = content[json_start:json_end + 1]

    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise LLMError(f"LLM returned malformed JSON: {e}\nRaw response: {content[:500]}")


# ─── Public API ───────────────────────────────────────────────────────────────

def get_edit_plan(
    cv_text: str,
    job_description: str,
    entity_map: dict,
    max_edits: int = MAX_EDITS,
) -> dict[str, Any]:
    """
    LLM Call 1: Generate an analysis and edit plan.

    Args:
        cv_text: Plain text CV content extracted from the uploaded PDF.
        job_description: Raw job description text.
        entity_map: Parsed entity map from cv_parser.parse_cv().
        max_edits: Maximum edits allowed.

    Returns:
        Parsed dict with 'analysis', 'edit_plan', 'total_edits'.

    Raises:
        LLMError: If the API call fails.
    """
    system_prompt = SYSTEM_PROMPT_CALL_1.format(
        max_edits=max_edits,
        companies=entity_map.get("companies", []),
        roles=entity_map.get("roles", []),
        technologies=entity_map.get("technologies", []),
        schema=EDIT_PLAN_SCHEMA,
    )
    user_prompt = USER_PROMPT_CALL_1.format(
        job_description=job_description,
        cv_text=cv_text,
        max_edits=max_edits,
    )

    return _call_api(system_prompt, user_prompt, temperature=0.3)


def get_modified_outputs(
    cv_text: str,
    edit_plan: dict,
    job_description: str,
) -> dict[str, Any]:
    """
    LLM Call 2: Apply the validated edit plan and generate LaTeX CV + cover letter.

    Args:
        cv_text: Plain text CV content extracted from the uploaded PDF.
        edit_plan: Validated edit plan dict from get_edit_plan().
        job_description: Raw job description (for cover letter context only).

    Returns:
        Parsed dict with 'modified_cv_latex', 'cover_letter_text', 'key_changes_summary'.

    Raises:
        LLMError: If the API call fails.
    """
    # Read the user's LaTeX template if present
    template_path = Path(__file__).parent.parent / "template.tex"
    if template_path.exists():
        template_text = template_path.read_text(encoding="utf-8")
    else:
        # Fallback: legacy default template (moderncv classic/blue)
        template_text = r"""\documentclass[11pt,a4paper,sans]{moderncv}
\moderncvstyle{classic}
\moderncvcolor{blue}
\usepackage[scale=0.75]{geometry}
\name{[FIRST]}{[LAST]}
\address{[ADDRESS]}{}{}
\phone[mobile]{[PHONE]}
\email{[EMAIL]}
\social[linkedin]{[LINKEDIN]}
\social[github]{[GITHUB]}
\begin{document}
\makecvtitle
\section{Summary}
[SUMMARY_TEXT]
\section{Experience}
\section{Projects}
\section{Skills}
\section{Education}
\end{document}"""

    system_prompt = SYSTEM_PROMPT_CALL_2.format(
        template=template_text,
        schema=OUTPUT_SCHEMA,
    )
    user_prompt = USER_PROMPT_CALL_2.format(
        cv_text=cv_text,
        edit_plan_json=json.dumps(edit_plan, indent=2),
        job_description=job_description,
    )

    return _call_api(system_prompt, user_prompt, temperature=0.2)
