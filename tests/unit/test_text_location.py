import pytest

from common.enums import RemoteType
from connectors.location import parse_location
from connectors.text import detect_remote_type, extract_min_years, html_to_text, title_matches


def test_html_to_text_handles_escaped_greenhouse_html():
    raw = (
        "&lt;h2&gt;About&lt;/h2&gt;&lt;p&gt;We build&amp;nbsp;cloud.&lt;/p&gt;"
        "&lt;ul&gt;&lt;li&gt;AWS&lt;/li&gt;&lt;/ul&gt;"
    )
    assert html_to_text(raw, escaped=True) == "About\n\nWe build cloud.\n\n- AWS"


def test_html_to_text_drops_scripts():
    assert html_to_text("<p>Hi</p><script>alert(1)</script>") == "Hi"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("You have 8+ years of experience in cloud.", 8),
        ("Minimum 5 years experience; ideally 10+ years of relevant experience", 5),
        ("3-5 years of professional experience", 3),
        ("mindestens 6 Jahre Berufserfahrung", 6),
        ("Founded 25 years ago, we have 300 employees", None),
        ("", None),
    ],
)
def test_extract_min_years(text, expected):
    assert extract_min_years(text) == expected


@pytest.mark.parametrize(
    "texts,expected",
    [
        (("Berlin (Hybrid)",), RemoteType.HYBRID),
        (("Remote - EMEA",), RemoteType.REMOTE),
        (("On-site, Dublin",), RemoteType.ONSITE),
        (("Berlin",), RemoteType.UNKNOWN),
    ],
)
def test_detect_remote_type(texts, expected):
    assert detect_remote_type(*texts) == expected


def test_title_matching_is_word_based_and_order_free():
    kw = ["cloud architect", "devops architect"]
    assert title_matches("Senior Cloud Solutions Architect (m/w/d)", kw)
    assert title_matches("Architect, DevOps Platform", kw)
    assert not title_matches("Cloud Support Engineer", kw)
    assert not title_matches("Senior Cloud Architect", kw, excluded=["senior"])
    assert title_matches("Anything", [])


@pytest.mark.parametrize(
    "value,country,city,europe",
    [
        ("Berlin, Germany", "DE", "Berlin", False),
        ("Paris, Paris, France", "FR", "Paris", False),
        ("Amsterdam", "NL", "Amsterdam", False),
        ("München", "DE", "Munchen", False),
        ("Remote - EMEA", None, None, True),
        ("Dublin, IE", "IE", "Dublin", False),
        ("Luxembourg", "LU", None, False),
        ("São Paulo, Brazil", None, None, False),
        ("New York, NY", None, None, False),
    ],
)
def test_parse_location(value, country, city, europe):
    loc = parse_location(value)
    assert (loc.country, loc.city, loc.europe_wide) == (country, city, europe)


def test_parse_location_uses_default_only_when_nothing_found():
    assert parse_location("Leipzig", default_country="DE").country == "DE"
    assert parse_location("Somewhere", default_country="DE").country == "DE"
    assert parse_location("Remote, Europe", default_country="DE").country is None
    assert parse_location("Paris", default_country="DE").country == "FR"
