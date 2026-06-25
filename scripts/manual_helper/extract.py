
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

def cmd_extract_tasks(args):
    """extract-tasks <spec.md> [...]"""
    import subprocess
    script = Path(__file__).resolve().parent / "extract-tasks.py"
    r = subprocess.run([sys.executable, str(script)] + list(args), capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def cmd_extract_fields(args):
    """extract-fields [--vue|--java] <path> [...]"""
    import subprocess
    script = Path(__file__).resolve().parent / "extract-fields.py"
    r = subprocess.run([sys.executable, str(script)] + list(args), capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def cmd_extract_routes(args):
    """extract-routes <router-file>"""
    import subprocess
    script = Path(__file__).resolve().parent / "extract-routes.py"
    r = subprocess.run([sys.executable, str(script)] + list(args), capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def cmd_extract_roles(args):
    """extract-roles <backend-root> [<frontend-root>]"""
    import subprocess
    script = Path(__file__).resolve().parent / "extract-roles.py"
    r = subprocess.run([sys.executable, str(script)] + list(args), capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def cmd_extract_openapi(args):
    """extract-openapi <openapi.yaml-or-json>"""
    import subprocess
    script = Path(__file__).resolve().parent / "extract-openapi.py"
    r = subprocess.run([sys.executable, str(script)] + list(args), capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


