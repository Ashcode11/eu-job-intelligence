"""Visa Intelligence Agent: classify a job's work-authorization stance from evidence.

Rules come first. The LLM is consulted only when the text mentions visas or relocation in
words the rules don't recognise, and its answer is accepted only if its quote appears
verbatim in the job description. A company is never treated as a sponsor because it
employs international staff; only explicit text or a documented public record counts.
"""

import hashlib
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from agents.llm.ollama import LLMUnavailable, OllamaClient
from agents.visa_intelligence.rules import AMBIGUOUS_HINTS, find_signals
from common.enums import VisaClassification as VC

ANALYZER_VERSION = "visa-1.0"
PATHWAYS_FILE = Path(__file__).resolve().parents[2] / "data" / "visa_pathways.json"

_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "classification": {"type": "string", "enum": [c.value for c in VC]},
        "quote": {"type": "string", "description": "exact sentence copied from the job text"},
        "rationale": {"type": "string"},
    },
    "required": ["classification", "quote", "rationale"],
}


@dataclass
class VisaResult:
    classification: VC
    mentions_sponsorship: bool | None = None
    relocation_support: bool | None = None
    non_eu_applicants_accepted: bool | None = None
    eu_authorization_required: bool | None = None
    employer_documented_sponsor: bool | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    country_pathways: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.5
    rationale: str = ""
    method: str = "rules"
    input_hash: str = ""
    llm_model: str | None = None
    local_language_required: bool = False


@lru_cache
def _pathways() -> dict[str, list[dict[str, Any]]]:
    data = json.loads(PATHWAYS_FILE.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def pathways_for(country: str | None) -> list[dict[str, Any]]:
    return [{**p, "country": country} for p in _pathways().get(country or "", [])]


def input_hash(content_hash: str, documented_sponsor: bool | None) -> str:
    return hashlib.sha256(
        f"{ANALYZER_VERSION}|{content_hash}|{documented_sponsor}".encode()
    ).hexdigest()


def classify(
    description: str,
    *,
    job_url: str,
    country: str | None,
    content_hash: str,
    documented_sponsor: bool | None = None,
    documented_sponsor_evidence: list[dict[str, Any]] | None = None,
) -> VisaResult:
    signals = find_signals(description)
    kinds = {s for s, _ in signals}
    evidence = [{"url": job_url, "quote": q, "signal": s} for s, q in signals]
    if documented_sponsor:
        for ev in documented_sponsor_evidence or []:
            evidence.append(
                {"url": ev.get("url"), "quote": ev.get("quote", ""), "signal": "documented_sponsor"}
            )

    r = VisaResult(
        classification=VC.NOT_MENTIONED,
        evidence=evidence,
        country_pathways=pathways_for(country),
        employer_documented_sponsor=documented_sponsor,
        input_hash=input_hash(content_hash, documented_sponsor),
        local_language_required="local_language_required" in kinds,
    )
    positive = "sponsorship_positive" in kinds
    negative = "sponsorship_negative" in kinds
    auth_required = "authorization_required" in kinds
    relocation = "relocation_support" in kinds
    welcome = "non_eu_welcome" in kinds

    r.relocation_support = (
        True
        if relocation or positive and "relocat" in _quotes(signals, "sponsorship_positive")
        else None
    )
    r.mentions_sponsorship = True if positive else (False if negative else None)
    r.eu_authorization_required = True if (auth_required or negative) else None
    r.non_eu_applicants_accepted = (
        False if (auth_required or negative) else (True if (welcome or positive) else None)
    )

    if "citizenship_or_clearance_required" in kinds:
        r.classification, r.confidence = VC.NOT_SUITABLE, 0.85
        r.rationale = (
            "The posting requires a specific citizenship or a security clearance, "
            "which work-permit sponsorship cannot provide."
        )
    elif negative or auth_required:
        # Contradictions ("relocation help, but no visa sponsorship") resolve to the negative.
        r.classification, r.confidence = VC.EU_AUTHORIZATION_REQUIRED, 0.9
        r.rationale = (
            "The posting states that sponsorship is not offered or that an "
            "existing right to work is required."
        )
    elif positive:
        r.classification, r.confidence = VC.EXPLICIT_SPONSORSHIP, 0.9
        r.rationale = "The posting explicitly offers visa or work-permit sponsorship."
    elif relocation or welcome or documented_sponsor:
        r.classification, r.confidence = VC.POTENTIAL_SPONSORSHIP, 0.5
        why = [
            w
            for w, ok in (
                ("relocation support is offered", relocation),
                ("international applicants are welcomed", welcome),
                ("the employer is a documented sponsor", documented_sponsor),
            )
            if ok
        ]
        r.rationale = (
            "Sponsorship is not stated explicitly, but " + " and ".join(why) + ". "
            "Confirm with the recruiter."
        )
    else:
        r.classification, r.confidence = VC.NOT_MENTIONED, 0.8
        r.rationale = "The posting does not mention visas, work permits or relocation."
    return r


async def refine_with_llm(result: VisaResult, description: str, llm: OllamaClient) -> VisaResult:
    """Only for 'not mentioned' results whose text still talks about immigration topics."""
    if result.classification != VC.NOT_MENTIONED or not AMBIGUOUS_HINTS.search(description):
        return result
    try:
        answer = await llm.chat_json(
            "You classify job postings by visa sponsorship stance. Use only the text given. "
            "Never infer sponsorship from company size or international staff. Copy the "
            "supporting sentence exactly.",
            "Categories: explicit_sponsorship, potential_sponsorship, "
            "eu_authorization_required, not_mentioned, not_suitable.\n\n"
            f"Job text:\n{description[:8000]}",
            _LLM_SCHEMA,
            max_tokens=300,
        )
    except LLMUnavailable:
        return result
    quote = " ".join(str(answer.get("quote", "")).split())
    haystack = " ".join(description.split())
    cls = answer.get("classification")
    if not quote or len(quote) < 15 or quote.lower() not in haystack.lower():
        result.rationale += " (An LLM suggestion was discarded: its quote is not in the text.)"
        return result
    if cls not in {c.value for c in VC}:
        return result
    result.classification = VC(cls)
    result.confidence = 0.6
    result.method = "rules+llm"
    result.llm_model = llm.chat_model
    result.rationale = str(answer.get("rationale", ""))[:500]
    result.evidence.append({"url": None, "quote": quote[:400], "signal": f"llm:{cls}"})
    return result


def _quotes(signals: list[tuple[str, str]], kind: str) -> str:
    return " ".join(q.lower() for s, q in signals if s == kind)
