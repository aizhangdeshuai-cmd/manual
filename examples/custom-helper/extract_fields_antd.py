"""Drop-in example: extract-fields adapted for Ant Design Vue.

This is NOT imported by the main skill. It is a reference implementation
showing how to add an Ant Design Vue <a-form-item> pattern to the main
extract-fields.py (see SKILL.md §0.6 / custom-helper README §1).

To use: copy the A_FORM_ITEM_RE and the loop into scripts/extract-fields.py
inside extract_from_vue(), then add a Vue file containing <a-form-item>
tags to the input. The shape of the output dicts matches the existing
Element Plus / naive-ui emitters.
"""
import re
import sys
from pathlib import Path

A_FORM_ITEM_RE = re.compile(
    r'<a-form-item[^>]*?name="(?P<name>[^"]+)"[^>]*?label="(?P<label>[^"]+)"',
    re.IGNORECASE,
)


def extract_from_antd_vue(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    fields = []
    for m in A_FORM_ITEM_RE.finditer(text):
        fields.append({
            "name": m.group("name"),
            "label": m.group("label"),
            "ui": "ant-design-vue",
            "source": str(path),
            "required_hint": 'rules=' in text[max(0, m.start() - 200): m.end()],
        })
    return fields


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: extract_fields_antd.py <file-or-dir> [more...]", file=sys.stderr)
        return 2
    roots = [Path(a) for a in argv[1:]]
    files: list[Path] = []
    for r in roots:
        if r.is_file():
            files.append(r)
        elif r.is_dir():
            files.extend(r.rglob("*.vue"))
    all_fields: list[dict] = []
    for f in files:
        all_fields.extend(extract_from_antd_vue(f))
    import json
    print(json.dumps(all_fields, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
