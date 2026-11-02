import pytest
from pydantic import ValidationError

from backend.schemas.candidate import CandidateUpdate
from common.config import Settings
from common.enums import DEFAULT_MATCH_WEIGHTS


def test_default_weights_sum_to_one():
    assert abs(sum(DEFAULT_MATCH_WEIGHTS.values()) - 1.0) < 1e-9


def test_weights_must_sum_to_one():
    bad = dict(DEFAULT_MATCH_WEIGHTS, technical_skills=0.5)
    with pytest.raises(ValidationError, match="sum to 1.0"):
        CandidateUpdate(match_weights=bad)


def test_weights_reject_unknown_keys():
    with pytest.raises(ValidationError, match="unknown"):
        CandidateUpdate(match_weights={**DEFAULT_MATCH_WEIGHTS, "vibes": 0.0})


def test_country_codes_uppercased_and_validated():
    assert CandidateUpdate(preferred_countries=["de", "nl"]).preferred_countries == ["DE", "NL"]
    with pytest.raises(ValidationError):
        CandidateUpdate(preferred_countries=["Germany"])


def test_unknown_authorization_stays_unset():
    body = CandidateUpdate(full_name="X")
    assert "has_eu_work_authorization" not in body.model_dump(exclude_unset=True)


def test_settings_split_comma_lists():
    s = Settings(api_keys="a, b,,c", cors_origins="http://x, http://y", _env_file=None)
    assert [k.get_secret_value() for k in s.api_keys] == ["a", "b", "c"]
    assert s.cors_origins == ["http://x", "http://y"]
