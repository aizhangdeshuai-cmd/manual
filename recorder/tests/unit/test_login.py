import pytest
from recorder_plugin.login import totp_code, validate_totp_secret


def test_validate_totp_secret_accepts_base32():
    assert validate_totp_secret("JBSWY3DPEHPK3PXP") is True


def test_validate_totp_secret_rejects_garbage():
    assert validate_totp_secret("not-valid-base32!!!") is False


def test_totp_code_returns_6_digits():
    code = totp_code("JBSWY3DPEHPK3PXP", timestamp=1234567890)
    assert len(code) == 6
    assert code.isdigit()


def test_totp_code_deterministic():
    code1 = totp_code("JBSWY3DPEHPK3PXP", timestamp=1234567890)
    code2 = totp_code("JBSWY3DPEHPK3PXP", timestamp=1234567890)
    assert code1 == code2


def test_totp_code_different_time_windows():
    code1 = totp_code("JBSWY3DPEHPK3PXP", timestamp=1234567890)
    code2 = totp_code("JBSWY3DPEHPK3PXP", timestamp=1234567890 + 60)
    assert code1 != code2


def test_totp_codes_with_drift_returns_three():
    from recorder_plugin.login import totp_codes_with_drift
    codes = totp_codes_with_drift("JBSWY3DPEHPK3PXP", drift=1, timestamp=1234567890)
    assert len(codes) == 3
    assert codes[0] != codes[1] or codes[1] != codes[2]  # at least one differs at boundary


def test_resolve_credential_passthrough():
    from recorder_plugin.login import resolve_credential
    assert resolve_credential("plain-value") == "plain-value"


def test_resolve_credential_from_env():
    from recorder_plugin.login import resolve_credential
    assert resolve_credential("$X", env={"X": "hello"}) == "hello"


def test_resolve_credential_from_environ_fallback():
    import os
    from recorder_plugin.login import resolve_credential
    os.environ["REC_TEST_VAR"] = "from-env"
    assert resolve_credential("$REC_TEST_VAR") == "from-env"
    del os.environ["REC_TEST_VAR"]


def test_login_step_from_dict():
    from recorder_plugin.login import LoginStep
    step = LoginStep.from_dict({
        "url": "https://example.com/login",
        "user_field": "input[name='u']",
        "user": "$U",
        "pass_field": "input[name='p']",
        "pass": "$P",
        "submit_selector": "button[type='submit']",
    })
    assert step.url == "https://example.com/login"
    assert step.pass_ == "$P"
    assert step.totp_secret == ""


def test_login_step_from_dict_with_totp():
    from recorder_plugin.login import LoginStep
    step = LoginStep.from_dict({
        "url": "https://x",
        "user_field": "u",
        "user": "$U",
        "pass_field": "p",
        "pass": "$P",
        "submit_selector": "s",
        "totp_secret": "$S",
        "totp_drift_seconds": 2,
    })
    assert step.totp_secret == "$S"
    assert step.totp_drift_seconds == 2
