from recorder_plugin.retry import SelectorResolver, RetryPolicy


def test_resolver_first_variant_is_original():
    r = SelectorResolver()
    variants = r.variants("button:has-text('新增用户')")
    assert variants[0] == "button:has-text('新增用户')"


def test_resolver_no_less_specific_fallback():
    """Variants must be equal or greater specificity; no generic element selectors."""
    r = SelectorResolver()
    variants = r.variants("button:has-text('新增用户')")
    # 'button' alone (stripped of has-text) must NOT appear — too broad, would match wrong element
    assert "button" not in variants
    for v in variants:
        assert v == variants[0] or "新增用户" in v, f"variant {v!r} lost specificity"


def test_resolver_text_fallback():
    r = SelectorResolver()
    variants = r.variants("button:has-text('新增用户')")
    assert any("新增用户" in v for v in variants)


def test_resolver_role_fallback():
    r = SelectorResolver()
    variants = r.variants("button:has-text('Save')")
    assert any("role=button" in v for v in variants)


def test_resolver_partial_text_fallback():
    r = SelectorResolver()
    variants = r.variants("button:has-text('Save User')")
    assert any("Save User" in v for v in variants)


def test_retry_policy_default_budget():
    p = RetryPolicy.auto()
    assert p.budget_per_tier == 2


def test_retry_policy_strict():
    p = RetryPolicy.strict()
    assert p.fail_fast is True


def test_resolver_attempt_returns_winning_selector():
    r = SelectorResolver()
    ok, winning, attempts = r.attempt(
        "button:has-text('Add')",
        lambda v: None,  # first variant always succeeds
    )
    assert ok is True
    assert winning == "button:has-text('Add')"
    assert attempts == 1


def test_resolver_attempt_retries_on_failure():
    r = SelectorResolver()
    calls: list[str] = []

    def fail_first_two_then_succeed(v):
        calls.append(v)
        if len([c for c in calls if c == v]) < 2:
            raise RuntimeError("not yet")

    ok, winning, attempts = r.attempt("button:has-text('Add')", fail_first_two_then_succeed)
    assert ok is True
    assert attempts == 2


def test_resolver_attempt_gives_up_after_all_variants():
    r = SelectorResolver()
    def always_fail(v):
        raise RuntimeError("nope")
    ok, winning, attempts = r.attempt("button:has-text('Missing')", always_fail)
    assert ok is False
    assert winning == ""
    assert attempts > 0
