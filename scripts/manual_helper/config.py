
from __future__ import annotations
import json
from pathlib import Path

def validate_config(project_root: Path) -> dict:
    """Validate manual-config.json + personas.json + business_objectives coverage.

    Returns a dict { ok: bool, errors: [str], warnings: [str], info: dict }.

    Hard rules (errors block validation):
      - manual-config.json exists, valid JSON, has required top-level fields
      - personas.json exists, valid JSON, has granularity + personas (>= 3)
      - Each persona has id, name, daily_tasks (>= 1)
      - business_objectives coverage: union of personas\' covers_objectives
        has >= 2 distinct values from the configured business_objectives list

    Soft rules (warnings only):
      - Personas with no covers_objectives (LLM may struggle to write tasks)
      - project.name still a <PLACEHOLDER> value
      - inputs paths still <PLACEHOLDER> values
    """
    errors, warnings, info = [], [], {}
    root = project_root

    cfg_path = root / "docs" / "user-manual" / "manual-config.json"
    personas_path = root / "docs" / "user-manual" / "personas.json"

    # ---- manual-config.json ----
    if not cfg_path.exists():
        errors.append(f"manual-config.json not found at {cfg_path}")
        return {"ok": False, "errors": errors, "warnings": warnings, "info": info}

    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f"manual-config.json is not valid JSON: {e}")
        return {"ok": False, "errors": errors, "warnings": warnings, "info": info}

    info["config_keys"] = sorted(cfg.keys())

    required_cfg_keys = ["project", "business_objectives", "personas_path", "inputs", "storage"]
    for k in required_cfg_keys:
        if k not in cfg:
            errors.append(f"manual-config.json missing required key: {k}")

    # project sub-keys
    proj = cfg.get("project", {})
    for pk in ["name", "display_name", "stack", "build_commands", "deploy"]:
        if pk not in proj:
            errors.append(f"manual-config.json project.* missing: {pk}")
    pn = proj.get("name", "")
    if isinstance(pn, str) and pn.startswith("<your-"):
        warnings.append(f"project.name still a placeholder: {pn!r}")

    # ---- personas.json ----
    if not personas_path.exists():
        errors.append(f"personas.json not found at {personas_path}")
        return {"ok": False, "errors": errors, "warnings": warnings, "info": info}

    try:
        pdata = json.loads(personas_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f"personas.json is not valid JSON: {e}")
        return {"ok": False, "errors": errors, "warnings": warnings, "info": info}

    granularity = pdata.get("granularity")
    if granularity not in ("role_only", "task_only", "role_with_tasks"):
        errors.append(
            f"personas.json granularity must be one of role_only / task_only / role_with_tasks, got {granularity!r}"
        )

    personas = pdata.get("personas", [])
    if not isinstance(personas, list) or len(personas) < 3:
        errors.append(f"personas.json must have >= 3 personas, got {len(personas)}")

    persona_ids = set()
    for i, p in enumerate(personas):
        if not isinstance(p, dict):
            errors.append(f"personas[{i}] is not an object")
            continue
        if "id" not in p or not p["id"]:
            errors.append(f"personas[{i}] missing id")
        else:
            persona_ids.add(p["id"])
        if "name" not in p or not p["name"]:
            errors.append(f"personas[{i}] missing name")
        if "daily_tasks" not in p or not isinstance(p["daily_tasks"], list) or not p["daily_tasks"]:
            errors.append(f"personas[{i}] (id={p.get('id')}) missing or empty daily_tasks")
        if "covers_objectives" not in p or not p["covers_objectives"]:
            warnings.append(
                f"personas[{i}] (id={p.get('id')}) has no covers_objectives; "
                f"LLM may not map this persona to a business objective"
            )

    # ---- business_objectives coverage ----
    business_objectives = cfg.get("business_objectives", [])
    if not business_objectives:
        errors.append("manual-config.json business_objectives must be a non-empty list")
    else:
        covered = set()
        for p in personas:
            for obj in p.get("covers_objectives", []):
                if obj in business_objectives:
                    covered.add(obj)
        if len(covered) < 2:
            errors.append(
                f"personas 覆盖的业务目标类别不足(<2),请调整 personas.json. "
                f"covered={sorted(covered)}, allowed={business_objectives}"
            )
        info["covered_objectives"] = sorted(covered)

    info["persona_ids"] = sorted(persona_ids)
    info["granularity"] = granularity

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "info": info,
    }


