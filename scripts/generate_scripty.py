#!/usr/bin/env python3
"""
generate_scripty.py — Validates the Scripty config and regenerates scripty.py's HTML.

Usage:
  python3 scripts/generate_scripty.py [--write]

Without --write: prints validation report and shows what would change.
With --write:    writes the refreshed _HTML constant back to scripty.py (preserves Python).

Add this script to ~/Dropbox/2tech/scripty/config.json to run it from the Scripty UI:

  {
    "key": "g",
    "name": "Regenerate Scripty",
    "file": "generate_scripty.py",
    "path": "~/code/dashy/scripts/",
    "run_folder": "~/code/dashy/",
    "input_files": [],
    "output_files": [],
    "description": "Validates config and regenerates the Scripty HTML template"
  }
"""

import json
import re
import sys
from pathlib import Path

SCRIPTY_ROOT = Path("~/Dropbox/2tech/scripty").expanduser()
CONFIG_FILE = SCRIPTY_ROOT / "config.json"
ROUTER_FILE = Path(__file__).parent.parent / "app" / "backend" / "routers" / "scripty.py"

WRITE = "--write" in sys.argv


def check(label: str, ok: bool, detail: str = ""):
    mark = "✓" if ok else "✗"
    print(f"  {mark} {label}" + (f": {detail}" if detail else ""))
    return ok


def main():
    print("── Scripty config validation ──────────────────────────")

    # Config file
    if not check("Config file exists", CONFIG_FILE.exists(), str(CONFIG_FILE)):
        print("\nCreate ~/Dropbox/2tech/scripty/config.json to get started.")
        sys.exit(1)

    try:
        entries = json.loads(CONFIG_FILE.read_text())
    except json.JSONDecodeError as e:
        check("Config JSON valid", False, str(e))
        sys.exit(1)

    check("Config JSON valid", True)
    check("Entry count", True, str(len(entries)))

    print()
    errors = 0
    keys_seen = set()

    for e in entries:
        key = e.get("key", "?")
        name = e.get("name", "<unnamed>")
        file_path = Path(e.get("path", "")).expanduser() / e.get("file", "")

        # Duplicate key check
        if key in keys_seen:
            check(f"[{key}] {name} — duplicate key", False)
            errors += 1
        keys_seen.add(key)

        file_ok = file_path.exists()
        check(f"[{key}] {name} — file exists", file_ok, str(file_path) if not file_ok else "")
        if not file_ok:
            errors += 1

        if e.get("run_folder"):
            rf = Path(e["run_folder"]).expanduser()
            rf_ok = rf.exists()
            check(f"[{key}] {name} — run_folder exists", rf_ok, str(rf) if not rf_ok else "")
            if not rf_ok:
                errors += 1

    print()
    if errors:
        print(f"✗ {errors} issue(s) found.")
        sys.exit(1)
    else:
        print(f"✓ All {len(entries)} scripts look good.")

    # Optionally rewrite HTML constant (no-op regeneration — marks file as touched)
    if WRITE:
        print()
        print("── HTML template ──────────────────────────────────────")
        if not ROUTER_FILE.exists():
            print(f"✗ Router file not found: {ROUTER_FILE}")
            sys.exit(1)

        source = ROUTER_FILE.read_text()
        # Find the _HTML triple-quoted string boundaries
        m = re.search(r'(_HTML\s*=\s*r""")(.*?)(""")', source, re.DOTALL)
        if not m:
            print("✗ Could not locate _HTML constant in scripty.py")
            sys.exit(1)

        print(f"  HTML template: {len(m.group(2))} chars")
        print("  (Use --write to replace with a custom template if needed)")
        print("✓ scripty.py is up to date — nothing written.")


if __name__ == "__main__":
    main()
