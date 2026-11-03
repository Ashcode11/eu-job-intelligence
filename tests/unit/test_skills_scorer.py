from agents.matching.scorer import CandidateFacts, JobFacts, SalaryFacts, VisaFacts, score
from agents.skills import canonical, extract_skills
from common.enums import DEFAULT_MATCH_WEIGHTS, InterviewLikelihood, RemoteType
from common.enums import VisaClassification as VC


def test_extract_skills_aliases_and_ambiguity():
    found = extract_skills("Hands-on with k8s, Amazon Web Services and Terraform; we use Golang.")
    assert {"Kubernetes", "AWS", "Terraform", "Go"} <= set(found)
    assert extract_skills("Let's go to the chef's table, stay safe.") == {}


def test_canonical():
    assert canonical("k8s") == "Kubernetes"
    assert canonical("azure") == "Microsoft Azure"
    assert canonical("Something Else") == "Something Else"


def _cand(**kw) -> CandidateFacts:
    base = dict(
        years_experience=12.0,
        skills={
            "AWS": 5,
            "Terraform": 5,
            "Kubernetes": 4,
            "Cloud Migration": 5,
            "AWS DMS": 4,
            "Microsoft Azure": 4,
        },
        target_roles=["Cloud Solutions Architect", "Cloud Migration Architect"],
        preferred_countries=["DE", "NL"],
        current_country="IN",
        open_to_relocation=True,
        requires_visa_sponsorship=True,
        has_eu_work_authorization=False,
        min_salary_eur=80000,
        designation="Cloud Architect",
        weights=dict(DEFAULT_MATCH_WEIGHTS),
    )
    base.update(kw)
    return CandidateFacts(**base)


def _job(**kw) -> JobFacts:
    base = dict(
        title="Senior Cloud Migration Architect (AWS)",
        description="Lead AWS migrations with Terraform, Kubernetes and AWS DMS.",
        required_skills=[],
        experience_min_years=8.0,
        seniority="senior",
        country="DE",
        remote_type=RemoteType.HYBRID,
        content_hash="h",
    )
    base.update(kw)
    return JobFacts(**base)


GOOD_VISA = VisaFacts(VC.EXPLICIT_SPONSORSHIP)
GOOD_SAL = SalaryFacts(True, 105000, None)


def test_strong_match_is_recommended_with_reasons():
    r = score(_cand(), _job(), GOOD_VISA, GOOD_SAL)
    assert r.overall_score >= 85 and r.recommended
    assert r.interview_likelihood == InterviewLikelihood.HIGH
    assert {"AWS", "Terraform", "Kubernetes", "AWS DMS"} <= set(r.matched_skills)
    assert any("sponsorship" in x for x in r.reasons_for)
    assert set(r.component_scores) == set(DEFAULT_MATCH_WEIGHTS)


def test_eu_authorization_required_is_a_blocker_for_sponsorship_seekers():
    r = score(_cand(), _job(), VisaFacts(VC.EU_AUTHORIZATION_REQUIRED), GOOD_SAL)
    assert r.overall_score <= 35 and not r.recommended
    assert r.interview_likelihood == InterviewLikelihood.LOW
    assert any("EU work authorization" in x for x in r.reasons_against)


def test_same_job_fine_for_candidate_with_eu_authorization():
    cand = _cand(requires_visa_sponsorship=False, has_eu_work_authorization=True)
    r = score(cand, _job(), VisaFacts(VC.EU_AUTHORIZATION_REQUIRED), GOOD_SAL)
    assert r.recommended and r.overall_score >= 80


def test_citizenship_requirement_is_hard_blocker():
    r = score(_cand(), _job(), VisaFacts(VC.NOT_SUITABLE), GOOD_SAL)
    assert r.overall_score <= 20


def test_unknown_authorization_is_not_penalised_but_noted():
    cand = _cand(requires_visa_sponsorship=None, has_eu_work_authorization=None)
    r = score(cand, _job(), VisaFacts(VC.EU_AUTHORIZATION_REQUIRED), GOOD_SAL)
    assert r.recommended
    assert any("Set your authorization" in x for x in r.reasons_against)


def test_experience_gap_and_missing_skills():
    job = _job(
        title="Principal Platform Architect",
        experience_min_years=15.0,
        description="Google Cloud, Pulumi and Go programming at scale.",
        seniority="principal",
    )
    r = score(_cand(), job, GOOD_VISA, GOOD_SAL)
    assert r.experience_gaps and r.component_scores["experience"] == 40.0
    assert "Pulumi" in r.missing_skills
    assert r.component_scores["technical_skills"] > 0  # GCP partially credited via AWS/Azure


def test_weights_change_the_score():
    low_sal = SalaryFacts(True, 60000, None)
    a = score(_cand(), _job(), GOOD_VISA, low_sal)
    heavy = dict(DEFAULT_MATCH_WEIGHTS, technical_skills=0.1, compensation=0.3)
    b = score(_cand(weights=heavy), _job(), GOOD_VISA, low_sal)
    assert b.overall_score < a.overall_score


def test_semantic_similarity_used_when_embeddings_exist():
    r = score(_cand(embedding=[1.0, 0.0]), _job(embedding=[1.0, 0.0]), GOOD_VISA, GOOD_SAL)
    assert r.semantic_similarity == 1.0 and r.component_scores["responsibilities"] == 100.0
    assert r.notes["responsibilities_method"] == "embedding similarity"


def test_input_hash_changes_with_profile():
    a = score(_cand(), _job(), GOOD_VISA, GOOD_SAL).input_hash
    b = score(_cand(min_salary_eur=120000), _job(), GOOD_VISA, GOOD_SAL).input_hash
    assert a != b
    assert a == score(_cand(), _job(), GOOD_VISA, GOOD_SAL).input_hash
