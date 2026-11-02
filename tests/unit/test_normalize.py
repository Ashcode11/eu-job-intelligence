from connectors.normalize import content_hash, dedup_hash, normalize_company_name, normalize_title


def test_company_suffixes_and_parens_removed():
    assert normalize_company_name("Nordlicht Cloud GmbH (sample)") == "nordlicht cloud"
    assert normalize_company_name("Grachten Digital B.V.") == "grachten digital"
    assert normalize_company_name("Revontuli Tech Oy") == "revontuli tech"


def test_company_unicode_folded():
    assert normalize_company_name("Müller & Söhne AG") == "muller sohne"


def test_title_gender_markers_and_abbreviations():
    assert normalize_title("Sr. Cloud Architect (m/w/d)") == "senior cloud architect"
    assert normalize_title("Senior Cloud Architect - f/m/d") == "senior cloud architect"


def test_dedup_hash_matches_same_role_across_sources():
    a = dedup_hash("Acme GmbH", "Sr. Cloud Architect (m/w/d)", "de", "München")
    b = dedup_hash("ACME", "Senior Cloud Architect", "DE", "Munchen")
    assert a == b


def test_dedup_hash_differs_by_city():
    assert dedup_hash("Acme", "Cloud Architect", "DE", "Berlin") != dedup_hash(
        "Acme", "Cloud Architect", "DE", "Munich"
    )


def test_content_hash_ignores_whitespace_only_changes():
    assert content_hash("Title", "Line one\n\nline two") == content_hash(
        "Title", "Line one line two"
    )
    assert content_hash("Title", "a") != content_hash("Title", "b")
