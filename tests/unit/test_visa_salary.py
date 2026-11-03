import json

import httpx
import pytest

from agents.llm.ollama import OllamaClient
from agents.salary_intelligence.analyzer import analyse, parse_salary_text
from agents.visa_intelligence.analyzer import classify, refine_with_llm
from common.config import Settings
from common.enums import VisaClassification as VC


def _visa(text, **kw):
    return classify(
        text, job_url="https://j.test/1", country=kw.pop("country", "DE"), content_hash="c", **kw
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        ("We offer visa sponsorship and relocation support.", VC.EXPLICIT_SPONSORSHIP),
        ("We are a recognised sponsor with the IND.", VC.EXPLICIT_SPONSORSHIP),
        (
            "We help you relocate to Berlin. International applicants are welcome.",
            VC.POTENTIAL_SPONSORSHIP,
        ),
        (
            "You must have the right to work in Ireland. We are unable to sponsor work permits.",
            VC.EU_AUTHORIZATION_REQUIRED,
        ),
        ("Candidates must already hold EU work authorization.", VC.EU_AUTHORIZATION_REQUIRED),
        ("Security clearance is required for this role.", VC.NOT_SUITABLE),
        ("Great team, modern stack, free coffee.", VC.NOT_MENTIONED),
    ],
)
def test_visa_classification(text, expected):
    assert _visa(text).classification == expected


def test_contradiction_resolves_to_negative():
    r = _visa("Relocation package available. Unfortunately we cannot offer visa sponsorship.")
    assert r.classification == VC.EU_AUTHORIZATION_REQUIRED
    assert r.relocation_support is True and r.mentions_sponsorship is False


def test_evidence_quotes_and_pathways():
    r = _visa("Nice office. We offer visa sponsorship for this role. Apply now.")
    assert r.evidence == [
        {
            "url": "https://j.test/1",
            "quote": "We offer visa sponsorship for this role.",
            "signal": "sponsorship_positive",
        }
    ]
    assert any("Blue Card" in p["name"] for p in r.country_pathways)


def test_international_staff_is_not_evidence():
    r = _visa("Our team has colleagues from 40 nationalities.")
    assert r.classification == VC.NOT_MENTIONED


def test_documented_sponsor_only_from_explicit_record():
    r = _visa(
        "Cloud role.",
        documented_sponsor=True,
        documented_sponsor_evidence=[{"url": "https://ind.nl/register", "quote": "Acme BV"}],
    )
    assert r.classification == VC.POTENTIAL_SPONSORSHIP
    assert r.evidence[0]["signal"] == "documented_sponsor"


def test_language_requirement_flagged():
    assert _visa("Fluency in Danish is required.").local_language_required


def _llm(answer: dict) -> OllamaClient:
    def handler(req: httpx.Request):
        return httpx.Response(
            200,
            json={
                "message": {"content": json.dumps(answer)},
                "prompt_eval_count": 100,
                "eval_count": 20,
            },
        )

    return OllamaClient(Settings(_env_file=None), transport=httpx.MockTransport(handler))


async def test_llm_refinement_accepts_verbatim_quote():
    text = "About us. Immigration paperwork can be arranged for the right person. Apply."
    base = _visa(text)
    assert base.classification == VC.NOT_MENTIONED
    llm = _llm(
        {
            "classification": "potential_sponsorship",
            "quote": "Immigration paperwork can be arranged for the right person.",
            "rationale": "Offers to arrange paperwork.",
        }
    )
    r = await refine_with_llm(base, text, llm)
    assert r.classification == VC.POTENTIAL_SPONSORSHIP and r.method == "rules+llm"
    assert llm.usage.calls == 1 and llm.usage.prompt_tokens == 100


async def test_llm_refinement_rejects_invented_quote():
    text = "About us. Immigration questions? Ask us anytime. Apply."
    llm = _llm(
        {
            "classification": "explicit_sponsorship",
            "quote": "We sponsor all visas for every candidate.",
            "rationale": "x",
        }
    )
    r = await refine_with_llm(_visa(text), text, llm)
    assert r.classification == VC.NOT_MENTIONED and "discarded" in r.rationale


async def test_llm_not_called_without_immigration_words():
    llm = _llm({"classification": "explicit_sponsorship", "quote": "x", "rationale": "x"})
    await refine_with_llm(_visa("Plain job text."), "Plain job text.", llm)
    assert llm.usage.calls == 0


@pytest.mark.parametrize(
    "text,lo,hi,cur,period",
    [
        ("EUR 85,000 - 105,000 gross per year", 85000, 105000, "EUR", "year"),
        ("EUR 90-115k", 90000, 115000, "EUR", None),
        ("70 000 - 80 000 SEK/month", 70000, 80000, "SEK", "month"),
        ("€75.000 p.a.", 75000, 75000, "EUR", "year"),
        ("£80k - £95k", 80000, 95000, "GBP", None),
    ],
)
def test_parse_salary_text(text, lo, hi, cur, period):
    p = parse_salary_text(text)
    assert (p.minimum, p.maximum, p.currency, p.period) == (lo, hi, cur, period)


def test_parse_salary_none():
    assert parse_salary_text("Competitive salary and great benefits") is None


def _sal(**kw):
    base = dict(
        country="DE",
        city="Berlin",
        seniority="senior",
        salary_min=None,
        salary_max=None,
        salary_currency=None,
        salary_period=None,
        salary_raw=None,
        candidate_min_salary_eur=80000,
    )
    base.update(kw)
    return analyse(**base)


def test_actual_salary_converted_and_kept_separate_from_estimate():
    r = _sal(country="SE", city="Stockholm", salary_raw="70 000 - 80 000 SEK/month")
    assert r.has_actual_salary and r.actual_min_eur == round(70000 * 12 * 0.087)
    assert r.estimated_min_eur is None and r.benchmark_median_eur is not None
    assert "fx" in r.assumptions and r.meets_candidate_minimum is True


def test_missing_salary_uses_estimate_and_flags_it():
    r = _sal()
    assert not r.has_actual_salary and r.assumptions["missing_salary"]
    assert r.estimated_min_eur < r.estimated_max_eur
    assert r.meets_candidate_minimum is None  # never decided from an estimate
    assert r.est_net_annual_eur and r.est_living_cost_annual_eur and r.est_savings_annual_eur
    assert "tax" in r.assumptions and "living_cost" in r.assumptions


def test_implausible_salary_rejected():
    r = _sal(salary_min=50, salary_max=60, salary_currency="EUR", salary_period="year")
    assert not r.has_actual_salary and "actual_rejected" in r.assumptions


def test_monthly_assumed_for_small_amounts():
    r = _sal(country="FI", city="Helsinki", salary_raw="6 500 - 8 000 EUR")
    assert r.actual_max_eur == 96000 and r.assumptions["period_assumed"] == "month"
