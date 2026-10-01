from app.lib.constraints import check_variant


def test_clean_discord_variant_has_no_violations():
    assert check_variant("discord", "short post", ["#a", "#b"]) == []


def test_x_max_length_violation_named():
    body = "x" * 281
    violations = check_variant("x", body, [])
    assert len(violations) == 1
    assert "max_length" in violations[0]
    assert "281" in violations[0]


def test_x_max_hashtags_violation_named():
    violations = check_variant("x", "short", ["#a", "#b", "#c", "#d"])
    assert any("max_hashtags" in v for v in violations)


def test_linkedin_forbids_shouting():
    violations = check_variant("linkedin", "THIS IS HUGE NEWS for everyone", [])
    assert any("forbid_shouting" in v for v in violations)


def test_linkedin_allows_short_acronyms():
    # 3-letter acronyms like 'CEO' or 'API' should not trip the shouting rule
    violations = check_variant("linkedin", "Our new CEO loves the API", [])
    assert violations == []


def test_unknown_platform_is_a_violation_not_a_crash():
    violations = check_variant("friendster", "hello", [])
    assert violations == ["unknown_platform:friendster"]


def test_multiple_violations_all_named_at_once():
    violations = check_variant("x", "x" * 300, ["#a", "#b", "#c", "#d"])
    assert len(violations) == 2
