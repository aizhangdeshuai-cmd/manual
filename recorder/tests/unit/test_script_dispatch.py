"""Contract tests for the script.py dispatch loop.

v0.2.4 audit round 3: the dispatch loop in `script.py:run_script` is
the single source of truth for which `action:` values are valid. A
mismatch between `ALLOWED_STEP_ACTIONS` and the actual `elif` branches
silently no-ops the step (C4 regression). These tests assert the two
lists stay in sync.
"""
import ast
from pathlib import Path
import pytest


SCRIPT_PY = Path(__file__).resolve().parents[2] / "recorder_plugin" / "script.py"


def _parse_script() -> ast.Module:
    return ast.parse(SCRIPT_PY.read_text())


def test_allowed_step_actions_set():
    """ALLOWED_STEP_ACTIONS must be a non-empty set of string literals."""
    tree = _parse_script()
    allowed = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "ALLOWED_STEP_ACTIONS"):
            allowed = ast.literal_eval(node.value)
    assert allowed is not None, "ALLOWED_STEP_ACTIONS not found"
    assert isinstance(allowed, set)
    assert all(isinstance(a, str) for a in allowed)
    # v0.3.9: 11 actions (added 'move' for explicit cursor move).
    assert len(allowed) == 11, f"expected 11 step actions, got {len(allowed)}: {allowed}"


def test_every_allowed_action_has_an_elif_branch():
    """For every action in ALLOWED_STEP_ACTIONS there must be an
    `elif action == "<name>":` branch in run_script's dispatch loop.
    C4 regression: set_viewport was in the set but had no elif →
    user-facing no-op."""
    tree = _parse_script()
    # Collect allowed action names
    allowed = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "ALLOWED_STEP_ACTIONS"):
            allowed = ast.literal_eval(node.value)
            break
    # Collect elif action == "<name>": branches
    found_in_dispatch = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            for child in ast.walk(node):
                if not isinstance(child, ast.Compare):
                    continue
                # Pattern: action == "X" (or "X" == action)
                left, right = child.left, child.comparators[0]
                if not (isinstance(left, ast.Name) and left.id == "action"):
                    continue
                if not isinstance(right, ast.Constant) or not isinstance(right.value, str):
                    continue
                found_in_dispatch.add(right.value)
    missing = allowed - found_in_dispatch
    assert not missing, (
        f"ALLOWED_STEP_ACTIONS contains {missing} but the dispatch loop "
        f"has no `elif action == ...` branch for them. These actions "
        f"will silently no-op (C4 regression)."
    )


def test_dispatch_branches_only_match_allowed_actions():
    """Reverse direction: every `elif action == "X"` branch should be
    listed in ALLOWED_STEP_ACTIONS (no orphan / dead dispatch)."""
    tree = _parse_script()
    allowed = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "ALLOWED_STEP_ACTIONS"):
            allowed = ast.literal_eval(node.value)
            break
    found_in_dispatch = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            for child in ast.walk(node):
                if not isinstance(child, ast.Compare):
                    continue
                left, right = child.left, child.comparators[0]
                if not (isinstance(left, ast.Name) and left.id == "action"):
                    continue
                if not isinstance(right, ast.Constant) or not isinstance(right.value, str):
                    continue
                found_in_dispatch.add(right.value)
    orphan = found_in_dispatch - allowed
    assert not orphan, (
        f"dispatch loop has `elif action == {orphan}` branch but those "
        f"actions are not in ALLOWED_STEP_ACTIONS. Either add to the "
        f"whitelist (preferred) or remove the dead branch."
    )


def test_script_module_imports_sys():
    """C1: script.py uses `print(..., file=sys.stderr)` at line ~139
    for the ai_annotate TODO-prompt warning. A previous audit found
    the module did NOT `import sys` — every TODO prompt raised
    NameError, swallowed by the dispatch try/except. Lock the fix."""
    import recorder_plugin.script as s
    assert hasattr(s, "sys"), "recorder_plugin.script must have `sys` attribute"
    import sys
    assert s.sys is sys


# === v0.2.4 audit round 3: M4 (json.loads error handling) + L1 ===

def test_run_script_returns_error_envelope_on_missing_file():
    """M4: a missing script file must return a JSON-shaped error envelope
    (status='error', errors=[...]) instead of crashing asyncio.run
    with an uncaught FileNotFoundError."""
    import asyncio
    from recorder_plugin.script import run_script
    result = asyncio.run(run_script(Path("/tmp/this/does/not/exist/anywhere.json")))
    assert result["status"] == "error"
    assert any("not found" in e["error"] for e in result["errors"])


def test_run_script_returns_error_envelope_on_corrupt_json(tmp_path):
    """M4: a script that is not valid JSON must return a clean error
    envelope, not an uncaught JSONDecodeError."""
    import asyncio
    bad = tmp_path / "bad.json"
    bad.write_text("not json at all {")
    from recorder_plugin.script import run_script
    result = asyncio.run(run_script(bad))
    assert result["status"] == "error"
    assert any("parse" in e["error"].lower() or "decode" in e["error"].lower()
               for e in result["errors"])


def test_to_kebab_emits_warning_on_normalization_collision():
    """L1: distinct inputs that collapse to the same kebab form
    ('01 List', '01-List', '01List') must emit a stderr warning so
    the user knows their file will overwrite a previous step's."""
    import sys
    from recorder_plugin.script import _to_kebab
    # Capture stderr
    import io
    captured = io.StringIO()
    old_stderr = sys.stderr
    sys.stderr = captured
    try:
        _to_kebab("01 List")
    finally:
        sys.stderr = old_stderr
    assert "01-list" in captured.getvalue()
    assert "01 List" in captured.getvalue()


# === v0.2.4 audit round 3 follow-up: LLM-vision prerequisite doc ===

def test_skill_md_documents_llm_vision_prerequisite():
    """Lock the §15 prerequisite note that says AI annotation requires a
    vision-capable LLM. The user explicitly asked for this so that
    anyone hitting `skipped_missing_response` with a text-only model
    (Qwen, DeepSeek, MiniMax, etc.) has a single place in the docs
    to discover the cause and the workarounds."""
    skill_md = (Path(__file__).resolve().parents[2] / "SKILL.md").read_text()
    # The note must mention both the supported and unsupported model
    # families so the user can match their harness to one or the other.
    assert "vision-capable" in skill_md, (
        "SKILL.md §15 must call out the vision-capable LLM prerequisite"
    )
    # Concrete examples of text-only models that the user raised
    for name in ("Qwen 2.5/3", "DeepSeek V3/R1", "MiniMax"):
        assert name in skill_md, (
            f"SKILL.md §15 must list {name!r} as a text-only model "
            f"that cannot fulfill ai_annotate requests"
        )
    # Workarounds must be mentioned
    for workaround in ("switch the harness", "manually annotate", "omit"):
        assert workaround in skill_md, (
            f"SKILL.md §15 must mention the {workaround!r} workaround"
        )
