"""Salary Intelligence Agent.

Actual salary (what the posting advertises) and estimated salary (benchmarks) are kept
apart. Every estimate records the assumptions behind it.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

ANALYZER_VERSION = "salary-1.0"
REFERENCE_FILE = Path(__file__).resolve().parents[2] / "data" / "salary_reference.json"
PLAUSIBLE_ANNUAL_EUR = (15_000, 500_000)

_CURRENCY_WORDS = {
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "sek": "SEK",
    "kr": None,
    "dkk": "DKK",
    "nok": "NOK",
    "£": "GBP",
    "gbp": "GBP",
    "chf": "CHF",
    "pln": "PLN",
    "zł": "PLN",
    "$": "USD",
    "usd": "USD",
}
_PERIOD_WORDS = [
    ("hour", r"per hour|/\s*h(?:ou)?r\b|hourly|stunde"),
    ("day", r"per day|/\s*day|daily rate|tagessatz"),
    ("month", r"per month|/\s*month|/\s*mo\b|monthly|monat|månad|kuukau"),
    ("year", r"per year|/\s*y(?:ea)?r|annual|annually|p\.?a\.?|yearly|jahr"),
]
_NUM = r"(\d{1,3}(?:[ ., ]\d{3})+|\d+(?:[.,]\d+)?)\s*(k)?"
_RANGE = re.compile(_NUM + r"\s*(?:-|–|—|to|bis)\s*(?:[€£$]\s*)?" + _NUM, re.I)
_SINGLE = re.compile(
    r"(?:[€£$]\s*)" + _NUM + r"|" + _NUM + r"\s*(?:eur|euro|sek|dkk|chf|gbp)", re.I
)


@lru_cache
def reference() -> dict[str, Any]:
    return json.loads(REFERENCE_FILE.read_text())


@dataclass
class ParsedSalary:
    minimum: float
    maximum: float
    currency: str | None
    period: str | None


@dataclass
class SalaryResult:
    has_actual_salary: bool = False
    actual_min_eur: float | None = None
    actual_max_eur: float | None = None
    source_currency: str | None = None
    fx_rate_to_eur: float | None = None
    estimated_min_eur: float | None = None
    estimated_max_eur: float | None = None
    benchmark_median_eur: float | None = None
    benchmark_source: str | None = None
    est_net_annual_eur: float | None = None
    est_living_cost_annual_eur: float | None = None
    est_savings_annual_eur: float | None = None
    meets_candidate_minimum: bool | None = None
    assumptions: dict[str, Any] = field(default_factory=dict)
    input_hash: str = ""


def _to_number(raw: str, k: str | None) -> float:
    s = raw.replace(" ", " ").strip()
    if re.fullmatch(r"\d{1,3}(?:[ .,]\d{3})+", s):
        value = float(re.sub(r"[ .,]", "", s))
    else:
        value = float(s.replace(",", "."))
    return value * 1000 if k else value


def parse_salary_text(text: str | None) -> ParsedSalary | None:
    """'EUR 85,000 - 105,000 gross per year', '70 000 - 80 000 SEK/month', 'EUR 90-115k'."""
    if not text:
        return None
    lowered = text.lower()
    currency = None
    for word, code in _CURRENCY_WORDS.items():
        if code and re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", lowered):
            currency = code
            break
    period = next((p for p, rx in _PERIOD_WORDS if re.search(rx, lowered)), None)
    if m := _RANGE.search(text):
        k_shared = m.group(4) or m.group(2)
        lo = _to_number(m.group(1), m.group(2) or k_shared)
        hi = _to_number(m.group(3), m.group(4) or k_shared)
    elif m := _SINGLE.search(text):
        num, k = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        lo = hi = _to_number(num, k)
    else:
        return None
    if lo > hi:
        lo, hi = hi, lo
    return ParsedSalary(lo, hi, currency, period)


def _annual_eur(amount: float, currency: str, period: str, ref: dict) -> tuple[float, float]:
    rate = ref["fx_to_eur"][currency]
    return amount * ref["period_multiplier"][period] * rate, rate


def input_hash(job_fields: tuple, candidate_min: int | None) -> str:
    return hashlib.sha256(
        f"{ANALYZER_VERSION}|{job_fields}|{candidate_min}|{reference().get('as_of')}".encode()
    ).hexdigest()


def analyse(
    *,
    country: str | None,
    city: str | None,
    seniority: str | None,
    salary_min: float | None,
    salary_max: float | None,
    salary_currency: str | None,
    salary_period: str | None,
    salary_raw: str | None,
    candidate_min_salary_eur: int | None,
) -> SalaryResult:
    ref = reference()
    res = SalaryResult(
        input_hash=input_hash(
            (
                country,
                city,
                seniority,
                salary_min,
                salary_max,
                salary_currency,
                salary_period,
                salary_raw,
            ),
            candidate_min_salary_eur,
        )
    )
    a: dict[str, Any] = {
        "reference_as_of": ref["as_of"],
        "reference_note": "Rough approximations; see data/salary_reference.json",
    }

    # 1. Actual salary from the posting
    parsed = None
    if salary_min or salary_max:
        parsed = ParsedSalary(
            float(salary_min or salary_max),
            float(salary_max or salary_min),
            salary_currency,
            salary_period,
        )
        a["actual_source"] = "structured fields from the job source"
    elif parsed := parse_salary_text(salary_raw):
        a["actual_source"] = f"parsed from text: {salary_raw!r}"
    if parsed:
        currency = parsed.currency or _default_currency(country)
        period = parsed.period or ("month" if parsed.maximum < 20_000 else "year")
        if parsed.period is None:
            a["period_assumed"] = period
        if parsed.currency is None:
            a["currency_assumed"] = currency
        if currency in ref["fx_to_eur"] and period in ref["period_multiplier"]:
            lo, rate = _annual_eur(parsed.minimum, currency, period, ref)
            hi, _ = _annual_eur(parsed.maximum, currency, period, ref)
            if PLAUSIBLE_ANNUAL_EUR[0] <= hi <= PLAUSIBLE_ANNUAL_EUR[1]:
                res.has_actual_salary = True
                res.actual_min_eur, res.actual_max_eur = round(lo), round(hi)
                res.source_currency, res.fx_rate_to_eur = currency, rate
                a["actual_basis"] = f"gross, {period} x {ref['period_multiplier'][period]}"
                if currency != "EUR":
                    a["fx"] = f"1 {currency} = {rate} EUR (approximate)"
            else:
                a["actual_rejected"] = f"implausible annual amount ({round(hi)} EUR)"
        else:
            a["actual_rejected"] = f"unknown currency/period {currency}/{period}"
    if not res.has_actual_salary:
        a["missing_salary"] = True

    # 2. Benchmark (always computed, for comparison) and estimate when nothing is posted
    bench = ref["benchmarks_senior_cloud_architect_eur"].get(country or "")
    factor = ref["seniority_factor"].get(seniority or "senior", 1.0)
    if bench:
        p25, median, p75 = (round(x * factor) for x in bench)
        res.benchmark_median_eur = median
        res.benchmark_source = (
            f"approximate benchmark for {country}, senior cloud architect "
            f"x {factor} ({seniority or 'senior'} assumed)"
        )
        if not res.has_actual_salary:
            res.estimated_min_eur, res.estimated_max_eur = p25, p75
            a["estimate_basis"] = "benchmark p25-p75 (no salary in the posting)"

    # 3. Take-home and savings (from actual midpoint, else estimate midpoint)
    gross = _mid(res.actual_min_eur, res.actual_max_eur) or _mid(
        res.estimated_min_eur, res.estimated_max_eur
    )
    tax = ref["effective_tax_and_social_rate"].get(country or "")
    living = ref["living_cost_annual_eur"].get(f"{country}:{city}") or ref[
        "living_cost_annual_eur"
    ].get(country or "")
    if gross and tax is not None:
        res.est_net_annual_eur = round(gross * (1 - tax))
        a["tax"] = (
            f"flat effective rate {tax:.0%} (income tax + employee social "
            "contributions, single, no expat scheme)"
        )
        a["gross_used"] = "actual midpoint" if res.has_actual_salary else "estimated midpoint"
    if living:
        res.est_living_cost_annual_eur = living
        known_city = f"{country}:{city}" in ref["living_cost_annual_eur"]
        where = f"city: {city}" if known_city else "country average"
        a["living_cost"] = f"{living} EUR/yr, single, 1-bedroom ({where})"
    if res.est_net_annual_eur is not None and living:
        res.est_savings_annual_eur = res.est_net_annual_eur - living

    if candidate_min_salary_eur and res.has_actual_salary:
        res.meets_candidate_minimum = res.actual_max_eur >= candidate_min_salary_eur
    res.assumptions = a
    return res


def _mid(lo: float | None, hi: float | None) -> float | None:
    return (lo + hi) / 2 if lo is not None and hi is not None else None


def _default_currency(country: str | None) -> str:
    return {
        "SE": "SEK",
        "DK": "DKK",
        "NO": "NOK",
        "GB": "GBP",
        "CH": "CHF",
        "PL": "PLN",
        "CZ": "CZK",
        "HU": "HUF",
    }.get(country or "", "EUR")
