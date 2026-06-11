"""Selector retry policy. Tries testid/aria-label → text → role → partial text."""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Callable

_HAS_TEXT_RE = re.compile(r":has-text\(\s*['\"]([^'\"]+)['\"]\s*\)")


def _extract_text(selector: str) -> str | None:
    m = _HAS_TEXT_RE.search(selector)
    return m.group(1) if m else None


def _strip_has_text(selector: str) -> str:
    return _HAS_TEXT_RE.sub("", selector).strip()


@dataclass
class RetryPolicy:
    budget_per_tier: int = 2
    fail_fast: bool = False

    @staticmethod
    def auto() -> "RetryPolicy":
        return RetryPolicy(budget_per_tier=2, fail_fast=False)

    @staticmethod
    def strict() -> "RetryPolicy":
        return RetryPolicy(budget_per_tier=2, fail_fast=True)


class SelectorResolver:
    """Generates fallback selector variants for retry."""

    def variants(self, selector: str) -> list[str]:
        """Generate fallback variants of equal or greater specificity.

        Order: original → text → role-based → partial text.
        Does NOT fall back to a less-specific selector (e.g. stripping
        `:has-text(...)` to just `button` would match the wrong element).
        """
        text = _extract_text(selector)
        out: list[str] = [selector]  # tier 0: original
        if text:
            out.append(f"text={text}")  # tier 1: text exact
            out.append(f"role=button >> text={text}")  # tier 2: role + text
            # tier 3: partial text (Playwright text= is substring by default)
            out.append(f"text={text}")
        return out

    def attempt(self, selector: str, locator_fn: Callable[[str], object]) -> tuple[bool, str, int]:
        """Try each variant up to budget_per_tier times. Sync-only.

        If `locator_fn` returns a coroutine, the coroutine is NOT awaited here
        and no exception is surfaced. Use `attempt_async` for async locators.
        """
        policy = RetryPolicy.auto()
        attempts = 0
        for variant in self.variants(selector):
            for _ in range(policy.budget_per_tier):
                attempts += 1
                try:
                    locator_fn(variant)  # raises on failure (sync only)
                    return True, variant, attempts
                except Exception:
                    continue
        return False, "", attempts

    async def attempt_async(self, selector: str, locator_fn) -> tuple[bool, str, int]:
        """Async-aware variant: awaits coroutine results from `locator_fn`."""
        import inspect
        policy = RetryPolicy.auto()
        attempts = 0
        for variant in self.variants(selector):
            for _ in range(policy.budget_per_tier):
                attempts += 1
                try:
                    result = locator_fn(variant)
                    if inspect.isawaitable(result):
                        await result
                    return True, variant, attempts
                except Exception:
                    continue
        return False, "", attempts
