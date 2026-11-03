"""Evidence rules for visa / work-authorization signals in job descriptions.

Each rule yields a signal and the exact sentence it matched (the evidence). The patterns
were written for English and German postings, the most common in the target markets.
"""

import re
from dataclasses import dataclass

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True)
class Rule:
    signal: str
    pattern: re.Pattern[str]


def _r(signal: str, *alternatives: str) -> Rule:
    return Rule(signal, re.compile(r"\b(?:" + "|".join(alternatives) + ")", re.I))


_PLACES = (
    r"(?:the\s+)?(?:eu|eea|europe|germany|(?:the\s+)?netherlands|ireland|sweden|"
    r"denmark|finland|belgium|luxembourg|austria)"
)

RULES: tuple[Rule, ...] = (
    # Negative: sponsorship explicitly not offered
    _r(
        "sponsorship_negative",
        r"(?:not|unable to|cannot|can't|won't|will not|do not|don't|does not|are not able to)"
        r"\s+(?:be able to\s+)?(?:offer|provide|support|sponsor)\w*\s+(?:any\s+)?"
        r"(?:visa|work permit|sponsorship|immigration)",
        r"no\s+(?:visa\s+)?sponsorship",
        r"sponsorship\s+(?:is\s+)?not\s+(?:available|possible|offered|provided)",
        r"without\s+(?:the\s+need\s+for\s+)?(?:visa\s+)?sponsorship",
        r"keine\s+(?:visa|arbeitserlaubnis)\w*",
    ),
    # Existing right to work required
    _r(
        "authorization_required",
        r"(?:must|need to|should|required to)\s+(?:already\s+)?(?:have|hold|possess)\s+"
        r"(?:a\s+|an\s+|the\s+)?(?:valid\s+|existing\s+|full\s+|current\s+)?(?:\w+\s+)?"
        r"(?:right to work|work(?:ing)? (?:permit|authori[sz]ation|rights?|visa)|"
        r"residence permit)",
        r"(?:already\s+)?hold\s+(?:\w+\s+)?eu work authori[sz]ation",
        r"(?:valid|existing)\s+(?:eu\s+)?work (?:permit|authori[sz]ation)\s+(?:is\s+)?required",
        r"must already hold eu",
        r"eligib\w+ to work in " + _PLACES,
        r"(?:have|with|need|require[sd]?)\s+(?:the\s+)?right to work in " + _PLACES,
        r"(?:eu|eea)\s+(?:citizenship|passport)\s+(?:is\s+)?required",
        r"arbeitserlaubnis\s+(?:für\s+\w+\s+)?(?:ist\s+)?(?:erforderlich|voraussetzung)",
    ),
    # Hard blockers
    _r(
        "citizenship_or_clearance_required",
        r"security clearance (?:is\s+)?(?:required|needed|mandatory)",
        r"(?:must|need to) (?:hold|have|obtain) (?:a\s+)?(?:\w+\s+)?security clearance",
        r"sicherheitsüberprüfung",
        r"must be an? (?:eu|german|dutch|irish|swedish|danish|finnish|belgian|luxembourg)\w* "
        r"(?:citizen|national)",
        r"(?:eu|german|dutch) (?:citizenship|nationality) (?:is\s+)?required",
    ),
    # Positive: explicit sponsorship
    _r(
        "sponsorship_positive",
        r"(?:we|will|can|able to|happy to)\s+(?:offer|provide|support|sponsor)\w*\s+"
        r"(?:\w+\s+){0,3}(?:visa|work permit|blue card|sponsorship)",
        r"visa\s+sponsorship\s+(?:is\s+)?(?:available|offered|provided|possible)",
        r"(?:offer|provide|including|incl\.)\s+(?:full\s+)?(?:visa|work permit|blue card)\s+"
        r"(?:sponsorship|support|assistance|application)",
        r"sponsor(?:ship)? (?:for|of) (?:your\s+)?(?:visa|work permit|blue card)",
        r"recogni[sz]ed sponsor",
        r"support (?:with\s+)?(?:your\s+)?(?:\w+\s+)?(?:eu blue card|blue card|work permit|"
        r"visa|highly skilled migrant) applications?",
        r"visa(?:\s+and\s+|\s*&\s*|\s*/\s*)relocation (?:support|assistance|package)",
        r"relocation(?:\s+and\s+|\s*&\s*|\s*/\s*)visa (?:support|assistance|sponsorship)",
    ),
    # Relocation support
    _r(
        "relocation_support",
        r"relocation (?:support|assistance|package|bonus|budget|allowance)",
        r"(?:help|support|assist)\w* (?:you\s+)?(?:with\s+)?(?:your\s+)?relocat\w+",
        r"umzugs(?:hilfe|unterstützung|kosten)",
    ),
    # Non-EU applicants welcome
    _r(
        "non_eu_welcome",
        r"international (?:applicants|candidates|talent) (?:are\s+)?(?:welcome|encouraged)",
        r"(?:welcome|open to)\s+international (?:applicants|candidates)",
        r"candidates (?:from|based) outside (?:the\s+)?(?:eu|eea|europe) (?:are\s+)?"
        r"(?:welcome|considered|eligible)",
    ),
    # Language requirement (context, not a visa signal by itself)
    _r(
        "local_language_required",
        r"(?:fluen\w+|native|proficien\w+|business[- ]level|c1|c2)\s+(?:in\s+)?(?:\w+\s+){0,2}"
        r"(?:german|dutch|danish|swedish|finnish|french|luxembourgish)\b",
        r"(?:german|dutch|danish|swedish|finnish|french)\s+(?:\w+\s+){0,2}(?:is\s+)?"
        r"(?:required|mandatory|a must)",
    ),
)

# Words that suggest the text talks about immigration but no rule matched: ask the LLM.
AMBIGUOUS_HINTS = re.compile(
    r"\b(visa|sponsor\w*|work permit|blue card|relocat\w+|right to work|immigration|"
    r"residence permit|work authori[sz]ation)\b",
    re.I,
)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s.strip()]


def find_signals(text: str) -> list[tuple[str, str]]:
    """[(signal, quote)] with one quote per signal per sentence."""
    out: list[tuple[str, str]] = []
    for sentence in sentences(text):
        hits = {rule.signal for rule in RULES if rule.pattern.search(sentence)}
        if "sponsorship_negative" in hits:
            # "we cannot offer visa sponsorship" also contains "offer visa sponsorship"
            hits.discard("sponsorship_positive")
        out.extend((rule.signal, sentence[:400]) for rule in RULES if rule.signal in hits)
    return out
