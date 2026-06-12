"""Login step. Form fill from env vars or auth.json. TOTP via stdlib only."""
from __future__ import annotations
import base64
import hmac
import os
import struct
import time
from dataclasses import dataclass

TOTP_PERIOD = 30
TOTP_DIGITS = 6
# v0.2.4 audit: drift 1 → 2. Network/agent-loop latency plus the time
# the auth page takes to render the TOTP input and accept paste can
# easily push a 30-second window past its boundary. drift=2 gives
# 90s of slack (prev, current, next, next+1 — i.e. 4 candidates in
# totp_codes_with_drift), which is the standard recommended setting
# for headless automation against real TOTP-protected services.
TOTP_WINDOW_DRIFT = 2


def validate_totp_secret(secret: str) -> bool:
    """Validate a Base32 TOTP secret (no padding required)."""
    try:
        s = secret.strip().replace(" ", "").upper()
        padding = (8 - len(s) % 8) % 8
        s_padded = s + "=" * padding
        base64.b32decode(s_padded)
        return True
    except Exception:
        return False


def _hotp(secret: str, counter: int) -> str:
    s = secret.strip().replace(" ", "").upper()
    padding = (8 - len(s) % 8) % 8
    key = base64.b32decode(s + "=" * padding)
    counter_bytes = struct.pack(">Q", counter)
    h = hmac.new(key, counter_bytes, "sha1").digest()
    offset = h[-1] & 0x0F
    code_int = (struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** TOTP_DIGITS)
    return str(code_int).zfill(TOTP_DIGITS)


def totp_code(secret: str, timestamp: float | None = None) -> str:
    """Compute TOTP code at given timestamp (default: now)."""
    ts = timestamp if timestamp is not None else time.time()
    counter = int(ts) // TOTP_PERIOD
    return _hotp(secret, counter)


def totp_codes_with_drift(secret: str, drift: int = TOTP_WINDOW_DRIFT, timestamp: float | None = None) -> list[str]:
    """Return 2*drift+1 TOTP codes centered on the current window.

    With the default drift=2 this returns 5 codes (counter-2 ... counter+2).
    The caller (perform_login) uses the middle one; the rest are kept for
    manual debugging and for future retry paths.
    """
    ts = timestamp if timestamp is not None else time.time()
    counter = int(ts) // TOTP_PERIOD
    return [_hotp(secret, counter + d) for d in range(-drift, drift + 1)]


def resolve_credential(value: str, env: dict | None = None) -> str:
    """If `value` starts with $, look it up in env (or os.environ)."""
    if not value.startswith("$"):
        return value
    name = value[1:]
    if env and name in env:
        return env[name]
    return os.environ.get(name, "")


@dataclass
class LoginStep:
    url: str
    user_field: str
    user: str
    pass_field: str
    pass_: str
    submit_selector: str
    totp_secret: str = ""
    totp_drift_seconds: int = TOTP_WINDOW_DRIFT

    @staticmethod
    def from_dict(d: dict) -> "LoginStep":
        return LoginStep(
            url=d["url"],
            user_field=d["user_field"],
            user=d["user"],
            pass_field=d["pass_field"],
            pass_=d["pass"],
            submit_selector=d["submit_selector"],
            totp_secret=d.get("totp_secret", ""),
            totp_drift_seconds=d.get("totp_drift_seconds", TOTP_WINDOW_DRIFT),
        )


async def perform_login(recorder, step: LoginStep, env: dict | None = None) -> bool:
    """Navigate, fill the form, optionally compute TOTP, submit, verify success.

    Returns True if login succeeded.

    TOTP handling: computes 2*drift+1 codes (default 5 with drift=2) and
    submits the center one. If the server rejects it as expired, callers
    can re-invoke perform_login (the recorder loop does not retry by
    design — the agent loop decides retry policy).
    """
    user = resolve_credential(step.user, env)
    pw = resolve_credential(step.pass_, env)
    await recorder.navigate(step.url)
    await recorder.page.fill(step.user_field, user)
    await recorder.page.fill(step.pass_field, pw)
    if step.totp_secret:
        secret = resolve_credential(step.totp_secret, env)
        codes = totp_codes_with_drift(secret, drift=step.totp_drift_seconds)
        await recorder.page.fill("input[name='totp']", codes[step.totp_drift_seconds])
    await recorder.page.click(step.submit_selector)
    try:
        await recorder.page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    body_attr = await recorder.page.locator("body").get_attribute("data-logged-in")
    if body_attr == "true":
        return True
    try:
        error_visible = await recorder.page.locator("[data-testid='login-error']").is_visible()
        return not error_visible
    except Exception:
        return False
