"""Whitelisted wait predicates. v1 rejects custom_js."""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass
from typing import Any

ALLOWED_STRATEGIES = {"selector", "text", "networkidle", "timeout"}


@dataclass
class WaitSpec:
    strategy: str
    args: dict[str, Any]

    @staticmethod
    def from_dict(d: dict) -> "WaitSpec":
        strategy = d.get("strategy")
        if strategy not in ALLOWED_STRATEGIES:
            if strategy == "custom_js":
                raise ValueError(
                    "custom_js is not supported in v1 (security: arbitrary JS in JSON "
                    "scripts is a remote code execution surface). See spec §5.10."
                )
            raise ValueError(f"Unknown wait strategy: {strategy!r}; allowed: {sorted(ALLOWED_STRATEGIES)}")
        return WaitSpec(strategy=strategy, args={k: v for k, v in d.items() if k != "strategy"})


async def dispatch_wait(page, spec: WaitSpec) -> int:
    """Execute the wait. Returns elapsed_ms."""
    start = time.monotonic()
    if spec.strategy == "selector":
        selector = spec.args["selector"]
        state = spec.args.get("state", "visible")
        await page.locator(selector).wait_for(state=state, timeout=10000)
    elif spec.strategy == "text":
        text = spec.args["text"]
        exact = spec.args.get("exact", False)
        if exact:
            await page.get_by_text(text, exact=True).first.wait_for(timeout=10000)
        else:
            await page.get_by_text(text).first.wait_for(timeout=10000)
    elif spec.strategy == "networkidle":
        await page.wait_for_load_state("networkidle", timeout=10000)
    elif spec.strategy == "timeout":
        await asyncio.sleep(spec.args.get("ms", 1000) / 1000.0)
    else:
        raise ValueError(f"Unhandled strategy: {spec.strategy}")
    return int((time.monotonic() - start) * 1000)
