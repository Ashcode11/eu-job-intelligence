"""Resume text extraction and deterministic profile extraction."""

import io
import re
from typing import Any

from agents.skills import category_of, extract_skills

CERT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(rx, re.I))
    for name, rx in [
        (
            "AWS Certified Solutions Architect – Professional",
            r"aws certified solutions architect\W+professional|\bsap-c0\d\b",
        ),
        (
            "AWS Certified Solutions Architect – Associate",
            r"aws certified solutions architect\W+associate|\bsaa-c0\d\b",
        ),
        (
            "AWS Certified DevOps Engineer – Professional",
            r"aws certified devops engineer|\bdop-c0\d\b",
        ),
        ("AWS Certified Security – Specialty", r"aws certified security"),
        ("AWS Certified Database – Specialty", r"aws certified database"),
        ("Azure Solutions Architect Expert (AZ-305)", r"\baz-30[345]\b|azure solutions architect"),
        ("Azure Administrator (AZ-104)", r"\baz-104\b|azure administrator"),
        ("Azure DevOps Engineer Expert (AZ-400)", r"\baz-400\b|devops engineer expert"),
        ("Azure Fundamentals (AZ-900)", r"\baz-900\b|azure fundamentals"),
        ("Google Professional Cloud Architect", r"professional cloud architect"),
        ("Certified Kubernetes Administrator (CKA)", r"\bcka\b|certified kubernetes administrator"),
        ("Certified Kubernetes Application Developer (CKAD)", r"\bckad\b"),
        ("HashiCorp Terraform Associate", r"terraform associate"),
        ("TOGAF", r"\btogaf\b"),
        ("ITIL", r"\bitil\b"),
        ("PMP", r"\bpmp\b"),
        ("Certified ScrumMaster", r"\bcsm\b|scrum ?master"),
        ("CISSP", r"\bcissp\b"),
    ]
]

_YEARS_TOTAL = re.compile(
    r"(\d{1,2})\+?\s*(?:years|yrs)\s+(?:of\s+)?(?:\w+\s+){0,3}?(?:experience|expertise)", re.I
)
_YEAR_RANGE = re.compile(
    r"\b((?:19|20)\d{2})\s*(?:-|–|to)\s*((?:19|20)\d{2}|present|current|now|today)\b", re.I
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


class UnsupportedResume(Exception):
    pass


def extract_text(content: bytes, content_type: str) -> str:
    if content_type == "application/pdf" or content.startswith(b"%PDF-"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    elif content.startswith(b"PK"):
        from docx import Document

        doc = Document(io.BytesIO(content))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        text = "\n".join(parts)
    else:
        raise UnsupportedResume(f"Unsupported resume type {content_type}")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 50:
        raise UnsupportedResume(
            "Almost no text could be extracted (is this a scanned PDF? OCR is not supported)"
        )
    return text


def analyse_text(text: str, current_year: int) -> dict[str, Any]:
    """Deterministic facts from resume text. No LLM; the same file always yields the same."""
    skills = extract_skills(text)
    certifications = sorted({name for name, rx in CERT_PATTERNS if rx.search(text)})

    stated = [int(m.group(1)) for m in _YEARS_TOTAL.finditer(text) if 1 <= int(m.group(1)) <= 45]
    starts = []
    for m in _YEAR_RANGE.finditer(text):
        start = int(m.group(1))
        if 1970 <= start <= current_year:
            starts.append(start)
    span = current_year - min(starts) if starts else None
    years = max(stated) if stated else span

    return {
        "skills": [
            {"name": n, "mentions": c, "category": category_of(n)}
            for n, c in sorted(skills.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "certifications": certifications,
        "years_experience_stated": max(stated) if stated else None,
        "years_experience_from_dates": span,
        "years_experience": years,
        "has_email": bool(_EMAIL.search(text)),  # contact data itself is never copied out
        "word_count": len(text.split()),
    }
