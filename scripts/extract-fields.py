#!/usr/bin/env python3
"""Extract form-field metadata from .vue files and Java DTO classes.

Usage:
  extract-fields.py <path> [<path> ...]
  extract-fields.py --java <java-source-or-dir>
  extract-fields.py --vue  <vue-file-or-dir>

Each path is auto-detected by extension. Output: JSON array to stdout.

Vue mode (Element Plus / naive-ui / generic form):
  Scans for <el-form-item prop="X" label="Y"> / v-model="form.X" / rules entries.
  Output: {name, label, type, required, validator, placeholder, source}

Java DTO mode (JSR-303 / Jakarta validation):
  Scans @NotNull / @NotBlank / @NotEmpty / @Size / @Pattern / @Min / @Max
  and field declarations.
  Output: {name, java_type, required, validation, description, source}

Output schema (JSON array; one entry per form field):
  [
    {
      "source": "src/views/UserForm.vue",
      "field_name": "email",
      "label": "邮箱",
      "type": "输入框",
      "required": true,
      "options": [],
      "placeholder": "请输入邮箱",
      "description": "User email"
    }
  ]

Field reference:
- source: .vue or .java file path (str)
- field_name: prop / v-model binding name (str)
- label: human label from <el-form-item label> (str)
- type: 输入框/下拉/日期/密码/单选/... (str)
- required: detected from rules or * marker (bool)
- options: enum values for select/radio (list, possibly empty)
- placeholder: input placeholder (str)
- description: optional .java @Schema description (str, possibly empty)

Empty array [] is valid (no .vue or .java files found). Orchestrator should
log this and proceed with LLM-only field inference (SKILL.md section 5.3).

"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path


# ---------- Vue mode ----------

# Match <el-form-item prop="X" label="Y" ...> or with rules required
EL_FORM_ITEM_RE = re.compile(
    r'<el-form-item[^>]*?prop="(?P<name>[^"]+)"[^>]*?label="(?P<label>[^"]+)"',
    re.IGNORECASE,
)
EL_FORM_ITEM_LABEL_ONLY_RE = re.compile(
    r'<el-form-item[^>]*?label="(?P<label>[^"]+)"[^>]*?prop="(?P<name>[^"]+)"',
    re.IGNORECASE,
)
V_MODEL_RE = re.compile(r'v-model="(?P<expr>[^"]+)"', re.IGNORECASE)
NAIVE_FORM_ITEM_RE = re.compile(
    r'<n-form-item[^>]*?path="(?P<name>[^"]+)"[^>]*?label="(?P<label>[^"]+)"',
    re.IGNORECASE,
)
# Required heuristic: "required: true" in rules object OR has * after label
RULES_REQUIRED_RE = re.compile(
    r'rules:\s*\{[^}]*?(?P<name>\w+)\s*:\s*\[[^\]]*?\{[^{}]*?required\s*:\s*true',
    re.IGNORECASE | re.DOTALL,
)
PLACEHOLDER_RE = re.compile(r'placeholder="(?P<ph>[^"]+)"', re.IGNORECASE)
TYPE_FROM_LABEL_RE = re.compile(
    r'(?P<t>输入框|文本框|下拉|选择器|日期|时间|数字|开关|文本域|密码|单选|多选|文件|图片)',
    re.IGNORECASE,
)


def _infer_type(label: str) -> str:
    m = TYPE_FROM_LABEL_RE.search(label)
    if m:
        return m.group(1)
    if "密码" in label:
        return "密码"
    if any(k in label for k in ("选择", "下拉", "类型", "状态")):
        return "下拉选择"
    return "输入框"


def extract_from_vue(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")

    fields: dict[str, dict] = {}

    for m in EL_FORM_ITEM_RE.finditer(text) or EL_FORM_ITEM_LABEL_ONLY_RE.finditer(text):
        name = m.group("name")
        label = m.group("label")
        if name not in fields:
            fields[name] = {
                "name": name,
                "label": label,
                "type": _infer_type(label),
                "required": False,
                "placeholder": None,
                "source": str(path),
            }
        # placeholder (best effort from nearby)
        start = m.end()
        nearby = text[start:start + 200]
        pm = PLACEHOLDER_RE.search(nearby)
        if pm:
            fields[name]["placeholder"] = pm.group("ph")

    for m in NAIVE_FORM_ITEM_RE.finditer(text):
        name = m.group("name")
        label = m.group("label")
        if name not in fields:
            fields[name] = {
                "name": name,
                "label": label,
                "type": _infer_type(label),
                "required": False,
                "placeholder": None,
                "source": str(path),
            }

    for m in V_MODEL_RE.finditer(text):
        expr = m.group("expr")
        # form.X  -> X
        parts = expr.split(".")
        if len(parts) >= 2 and parts[0] in ("form", "modelForm", "dataForm"):
            name = parts[-1]
            if name not in fields:
                fields[name] = {
                    "name": name,
                    "label": name,
                    "type": "输入框",
                    "required": False,
                    "placeholder": None,
                    "source": str(path),
                }

    for m in RULES_REQUIRED_RE.finditer(text):
        name = m.group("name")
        if name in fields:
            fields[name]["required"] = True

    return list(fields.values())


# ---------- Java DTO mode ----------

FIELD_DECL_RE = re.compile(
    r"^\s*@?(?P<annotations>(?:@\w+(?:\([^)]*\))?\s+)*)"
    r"private\s+(?P<type>[\w<>,\s\[\].]+?)\s+(?P<name>\w+)\s*;",
    re.MULTILINE,
)
ANNOTATION_RE = re.compile(r"@(\w+)(?:\((?P<args>[^)]*)\))?")


def extract_from_java(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    fields: list[dict] = []
    for m in FIELD_DECL_RE.finditer(text):
        name = m.group("name")
        jtype = m.group("type").strip()
        annotations_str = m.group("annotations")
        annotations = ANNOTATION_RE.findall(annotations_str)
        required = any(a in ("NotNull", "NotBlank", "NotEmpty") for a, _ in annotations)
        validators = [a for a, _ in annotations if a in ("Size", "Pattern", "Min", "Max", "Email", "DecimalMin", "DecimalMax")]
        # Try to find Swagger / Schema description
        desc = None
        # search a few lines above for @Schema(description = "...")
        # Use m.start() of the field declaration (which skips past javadoc to the
        # annotations), but ALSO scan from m.start() forward to catch @Schema on
        # the line directly above the field.
        above_start = max(0, m.start() - 800)
        search_range = text[above_start:m.end() + 50]
        sd = re.search(r'@Schema\(.*?description\s*=\s*"([^"]+)"', search_range, re.DOTALL)
        if sd:
            desc = sd.group(1)
        fields.append({
            "name": name,
            "java_type": jtype,
            "required": required,
            "validators": validators,
            "description": desc,
            "source": str(path),
        })
    return fields


# ---------- CLI ----------

def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: extract-fields.py [--vue|--java] <path> [...]", file=sys.stderr)
        return 0
    mode = None
    paths: list[Path] = []
    for a in argv:
        if a in ("--vue", "--java"):
            mode = a[2:]
            continue
        paths.append(Path(a))

    out: list[dict] = []
    for p in paths:
        if p.is_dir():
            if mode == "vue" or (mode is None and "vue" in p.name):
                files = list(p.rglob("*.vue"))
            elif mode == "java" or (mode is None and "dto" in str(p).lower()):
                files = list(p.rglob("*.java"))
            else:
                files = list(p.rglob("*.vue")) + list(p.rglob("*.java"))
        else:
            files = [p]

        for f in files:
            if f.suffix == ".vue":
                out.extend(extract_from_vue(f))
            elif f.suffix == ".java":
                out.extend(extract_from_java(f))

    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
