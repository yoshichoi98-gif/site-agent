from src.schema import Evidence, SiteProfile


def test_evidence_defaults_to_not_found():
    e = Evidence()
    assert e.value is None
    assert e.source_url is None
    assert e.snippet is None
    assert e.confidence == "not_found"


def test_evidence_accepts_valid_confidence():
    for level in ("high", "medium", "low", "not_found"):
        e = Evidence(confidence=level)
        assert e.confidence == level


def test_site_profile_all_fields_default_to_not_found():
    p = SiteProfile()
    for field_name in SiteProfile.model_fields:
        evidence = getattr(p, field_name)
        assert evidence.confidence == "not_found", f"{field_name} should default to not_found"


def test_evidence_snippet_max_length():
    # 300 chars is allowed; 301 is not
    long_snippet = "x" * 300
    e = Evidence(snippet=long_snippet)
    assert len(e.snippet) == 300


def test_site_profile_with_data():
    p = SiteProfile(
        canonical_org_name=Evidence(
            value="Mayo Clinic",
            source_url="https://mayoclinic.org/about",
            snippet="Mayo Clinic is a nonprofit organization",
            confidence="high",
        )
    )
    assert p.canonical_org_name.value == "Mayo Clinic"
    assert p.hq_phone.confidence == "not_found"
