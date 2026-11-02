"""Normalisation and hashing used for deduplication across job sources."""

import hashlib
import re
import unicodedata

_LEGAL_SUFFIXES = re.compile(
    r"\b(gmbh|ag|se|b\.?v\.?|n\.?v\.?|ltd|limited|plc|ab|aps|a/s|oy|oyj|sa|s\.a\.|sarl|s\.a\.r\.l\.|"
    r"inc|llc|corp|corporation|co|company|group|holding|holdings)\b\.?",
    re.IGNORECASE,
)
_PARENS = re.compile(r"\([^)]*\)")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_TITLE_NOISE = re.compile(r"\b(m/w/d|w/m/d|f/m/d|m/f/d|m/f|f/m|all genders?|h/f|f/h)\b", re.I)
_SENIORITY_SYNONYMS = {"sr": "senior", "jr": "junior", "mgr": "manager", "eng": "engineer"}


def _ascii_fold(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()


def normalize_company_name(name: str) -> str:
    """'Nordlicht Cloud GmbH (sample)' -> 'nordlicht cloud'."""
    v = _ascii_fold(_PARENS.sub(" ", name)).lower()
    v = _LEGAL_SUFFIXES.sub(" ", v)
    return " ".join(_NON_ALNUM.sub(" ", v).split())


def normalize_title(title: str) -> str:
    """'Sr. Cloud Architect (m/w/d)' -> 'senior cloud architect'."""
    v = _TITLE_NOISE.sub(" ", _ascii_fold(title))
    v = _PARENS.sub(" ", v).lower()
    words = [_SENIORITY_SYNONYMS.get(w, w) for w in _NON_ALNUM.sub(" ", v).split()]
    return " ".join(words)


def dedup_hash(company: str | None, title: str, country: str | None, city: str | None) -> str:
    """Same role, same company, same place: one job, even when posted on several boards."""
    parts = [
        normalize_company_name(company or ""),
        normalize_title(title),
        (country or "").upper(),
        " ".join(_NON_ALNUM.sub(" ", _ascii_fold(city or "").lower()).split()),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def content_hash(*fields: str | None) -> str:
    """Changes whenever the substantive content changes, which triggers re-analysis."""
    joined = "\x1f".join(" ".join((f or "").split()) for f in fields)
    return hashlib.sha256(joined.encode()).hexdigest()
