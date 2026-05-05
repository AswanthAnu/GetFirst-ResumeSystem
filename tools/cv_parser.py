"""
cv_parser.py — Layer 3 Tool: CV Parser (PDF text + LaTeX)

Primary mode: Extract text from a PDF upload, then parse entity map.
Fallback mode: Parse entity map directly from LaTeX string (legacy).

Fully deterministic — no LLM involved.
"""

import re
import io
from typing import TypedDict


# ─── Entity Types ─────────────────────────────────────────────────────────────

class EntityMap(TypedDict):
    companies: list[str]
    roles: list[str]
    technologies: list[str]
    dates: list[str]
    sections: list[str]
    total_section_count: int


# ─── Tech Vocabulary (Curated) ────────────────────────────────────────────────

TECH_VOCABULARY: set[str] = {
    # Languages
    "python", "javascript", "typescript", "java", "c++", "c#", "go", "golang",
    "rust", "ruby", "php", "swift", "kotlin", "scala", "r", "matlab", "bash",
    "shell", "powershell", "sql", "html", "css", "sass", "scss",
    # Frameworks / Libraries
    "react", "next.js", "nextjs", "vue", "angular", "svelte", "django", "flask",
    "fastapi", "express", "node.js", "nodejs", "spring", "rails", "laravel",
    "tensorflow", "pytorch", "keras", "scikit-learn", "pandas", "numpy", "scipy",
    "langchain", "openai", "hugging face", "huggingface",
    # Databases
    "postgresql", "postgres", "mysql", "sqlite", "mongodb", "redis",
    "elasticsearch", "cassandra", "dynamodb", "firestore", "supabase", "prisma",
    # Cloud / DevOps
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform", "ansible",
    "ci/cd", "github actions", "jenkins", "circleci", "gitlab", "nginx",
    "linux", "ubuntu", "debian",
    # Tools / Platforms
    "git", "github", "gitlab", "bitbucket", "jira", "confluence", "figma",
    "postman", "graphql", "rest", "grpc", "kafka", "rabbitmq", "celery",
    "airflow", "spark", "hadoop", "tableau", "power bi",
    # AI / ML specific
    "llm", "gpt", "bert", "transformer", "rag", "vector database", "pinecone",
    "weaviate", "chromadb", "langsmith",
}

# Common suffixes that suggest a company name
COMPANY_SUFFIXES = {
    "ltd", "limited", "inc", "corp", "corporation", "llc", "plc",
    "group", "consulting", "solutions", "technologies", "tech",
    "systems", "services", "software", "labs", "ai", "digital",
    "agency", "studio", "ventures", "capital",
}

# Common section headings that should not be classified as roles or companies
SECTION_HEADING_KEYWORDS = {
    "experience", "education", "skills", "projects", "certifications",
    "awards", "languages", "interests", "publications", "references",
    "summary", "profile", "contact", "links", "achievements",
    "work experience", "professional experience", "technical skills",
    "personal projects", "open source", "volunteer", "leadership",
    "extracurricular", "honors", "fellowships", "patents",
}

# Common job title keywords
ROLE_KEYWORDS = {
    "engineer", "developer", "architect", "manager", "lead", "director",
    "analyst", "consultant", "scientist", "researcher", "designer",
    "specialist", "coordinator", "officer", "head", "vp", "president",
    "intern", "associate", "senior", "junior", "principal", "staff",
    "full stack", "fullstack", "frontend", "backend", "devops", "sre",
    "ml", "ai", "data", "cloud", "platform", "product", "project",
    "software", "site", "reliability",
}

# ─── PDF Extraction ───────────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """
    Extract plain text from a PDF file's bytes.

    Args:
        pdf_bytes: Raw bytes of the PDF file.

    Returns:
        Extracted plain text string, pages joined with newlines.

    Raises:
        ValueError: If the PDF cannot be read or yields no text.
    """
    try:
        import pdfplumber
    except ImportError:
        raise ImportError(
            "pdfplumber is not installed. Run: pip install pdfplumber"
        )

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = []
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())

    if not pages:
        raise ValueError(
            "Could not extract any text from the PDF. "
            "Make sure it's a text-based PDF (not a scanned image)."
        )

    return "\n\n".join(pages)


# ─── Date Patterns ────────────────────────────────────────────────────────────

DATE_PATTERNS = [
    r"\b\d{4}\s*[-–—]+\s*(?:present|current|now|ongoing)\b",   # 2020 – Present
    r"\b\d{4}\s*[-–—]+\s*\d{4}\b",                             # 2019 – 2023
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b",  # May 2022
]


# ─── Heuristic Entity Extraction (plain text) ─────────────────────────────────

def _extract_dates(text: str) -> list[str]:
    dates = []
    seen = set()
    for pattern in DATE_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            d = match.group(0).strip()
            if d.lower() not in seen:
                seen.add(d.lower())
                dates.append(d)
    return dates


def _extract_technologies(text: str) -> list[str]:
    text_lower = text.lower()
    # Also try a space-collapsed version for PDFs where pdfplumber merges words
    text_no_spaces = re.sub(r"\s+", "", text_lower)
    found = []
    for tech in TECH_VOCABULARY:
        if " " in tech:
            # Multi-word: try literal match (e.g. "github actions") and
            # space-collapsed match (e.g. "githubactions" from merged PDF text)
            if re.search(re.escape(tech), text_lower):
                found.append(tech)
            elif re.search(re.escape(tech.replace(" ", "")), text_no_spaces):
                found.append(tech)
        else:
            # Single-word: use word boundaries to avoid matching substrings
            # (e.g. "scala" should not match inside "scalable")
            if re.search(r"(?<!\w)" + re.escape(tech) + r"(?!\w)", text_lower):
                found.append(tech)
    return sorted(found)


def _extract_sections_from_text(text: str) -> list[str]:
    """
    Detect section headings from plain text CV.
    Heuristic: short ALL-CAPS lines or Title Case lines at start of line.
    """
    sections = []
    seen = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or len(stripped) > 50:
            continue
        # ALL CAPS line (common in PDFs compiled from LaTeX CVs)
        if stripped.isupper() and len(stripped) > 3:
            if stripped.lower() not in seen:
                seen.add(stripped.lower())
                sections.append(stripped.title())
        # Title Case with no lowercase words longer than 3 chars (likely a heading)
        elif re.match(r'^[A-Z][a-zA-Z\s&/]+$', stripped) and len(stripped.split()) <= 5:
            # Filter out single common words that aren't sections
            if stripped.lower() not in seen and len(stripped) > 4:
                seen.add(stripped.lower())
                sections.append(stripped)
    return sections


def _extract_roles_and_companies(text: str) -> tuple[list[str], list[str]]:
    """
    Extract job roles and company names from plain text CV.
    Strategy: look for lines near date patterns, then classify as role or company.
    """
    roles = []
    companies = []
    roles_seen: set[str] = set()
    companies_seen: set[str] = set()

    lines = text.splitlines()
    # Find line indices that contain dates
    date_line_indices = set()
    for i, line in enumerate(lines):
        for pattern in DATE_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                date_line_indices.add(i)
                # Also check adjacent lines
                for adj in [i - 1, i + 1, i - 2, i + 2]:
                    if 0 <= adj < len(lines):
                        date_line_indices.add(adj)

    # Classify lines near dates as role or company
    for i in date_line_indices:
        line = lines[i].strip()
        if not line or len(line) > 80 or len(line) < 3:
            continue

        line_lower = line.lower()

        # Skip lines that are themselves dates
        is_date = any(re.search(p, line, re.IGNORECASE) for p in DATE_PATTERNS)
        if is_date:
            continue

        # Skip lines that are section headings
        if line_lower in SECTION_HEADING_KEYWORDS:
            continue

        # Check if it looks like a job role
        # Use word boundaries for single-word keywords to avoid substring false
        # positives (e.g. "data" matching inside "datasets", "ml" inside "xml")
        has_role_keyword = False
        for kw in ROLE_KEYWORDS:
            if " " in kw:
                if kw in line_lower:
                    has_role_keyword = True
                    break
            elif re.search(r"\b" + re.escape(kw) + r"\b", line_lower):
                has_role_keyword = True
                break
        if has_role_keyword and line_lower not in roles_seen:
            # Clean it up: take just the role part (before any comma or pipe)
            role = re.split(r'[,|·•@]', line)[0].strip()
            if role and len(role) > 3:
                roles_seen.add(role.lower())
                roles.append(role)
            continue

        # Check if it looks like a company name (Title Case, possibly with known suffix)
        words = line.split()
        is_title_case = all(w[0].isupper() for w in words if w and w[0].isalpha())
        has_company_suffix = any(line_lower.rstrip('.,').endswith(s) for s in COMPANY_SUFFIXES)

        if (is_title_case or has_company_suffix) and line_lower not in companies_seen:
            company = re.split(r'[,|·•@]', line)[0].strip()
            if company and len(company) > 2:
                companies_seen.add(company.lower())
                companies.append(company)

    return roles, companies


# ─── Main Public API ──────────────────────────────────────────────────────────

def parse_cv(text: str) -> EntityMap:
    """
    Parse a plain-text CV string (extracted from PDF) and return a structured EntityMap.

    Also accepts LaTeX strings (auto-detected by presence of \\begin{document}).
    For LaTeX strings, strips commands before entity extraction.

    Args:
        text: Plain text CV content (from PDF extraction) or LaTeX string.

    Returns:
        EntityMap with companies, roles, technologies, dates, sections.
    """
    # Auto-detect LaTeX and strip commands for cleaner analysis
    if r"\begin{document}" in text or r"\documentclass" in text:
        # Strip LaTeX commands to get plain text for analysis
        plain = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?\{([^}]*)\}", r"\2", text)
        plain = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", plain)
        plain = re.sub(r"[{}]", " ", plain)
    else:
        plain = text

    dates = _extract_dates(plain)
    technologies = _extract_technologies(plain)
    sections = _extract_sections_from_text(plain)
    roles, companies = _extract_roles_and_companies(plain)

    return EntityMap(
        companies=companies,
        roles=roles,
        technologies=technologies,
        dates=dates,
        sections=sections,
        total_section_count=len(sections),
    )


# ─── CLI Test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import json
    from pathlib import Path

    # Check for a PDF argument
    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1])
        if not pdf_path.exists():
            print(f"❌ File not found: {pdf_path}")
            sys.exit(1)

        print(f"Extracting text from: {pdf_path}")
        pdf_bytes = pdf_path.read_bytes()
        cv_text = extract_text_from_pdf(pdf_bytes)
        print(f"Extracted {len(cv_text)} characters\n")
    else:
        # Check for master_cv.pdf in project root
        pdf_path = Path(__file__).parent.parent / "master_cv.pdf"
        if pdf_path.exists():
            print(f"Extracting from: {pdf_path}")
            cv_text = extract_text_from_pdf(pdf_path.read_bytes())
        else:
            print("Usage: python tools/cv_parser.py <path/to/cv.pdf>")
            print("       or place master_cv.pdf in the project root.")
            sys.exit(1)

    entity_map = parse_cv(cv_text)
    print("=" * 50)
    print("CV Parser — Entity Map")
    print("=" * 50)
    print(json.dumps(entity_map, indent=2))
    print(f"\n✅ Parsed {entity_map['total_section_count']} sections, "
          f"{len(entity_map['companies'])} companies, "
          f"{len(entity_map['roles'])} roles, "
          f"{len(entity_map['technologies'])} technologies, "
          f"{len(entity_map['dates'])} dates.")
