"""Console wrappers around the in-repo scripts.

These entry points expect an editable install (`pip install -e .`) so the
hyphenated tool directories sit next to this package.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def _repo_root() -> Path:
    root = Path(__file__).resolve().parent.parent
    if not (root / "web-scraper" / "scraper.py").is_file():
        raise SystemExit(
            "Console commands require an editable install of this repository "
            "(pip install -e .). Run the scripts directly, for example: "
            "python web-scraper/scraper.py"
        )
    return root


def _run(rel_dir: str, filename: str) -> None:
    root = _repo_root()
    script_dir = root / rel_dir
    sys.path.insert(0, str(script_dir))
    runpy.run_path(str(script_dir / filename), run_name="__main__")


def web_scraper() -> None:
    _run("web-scraper", "scraper.py")


def to_dojo() -> None:
    _run("to-dojo", "to_dojo.py")


def desktop_assistant() -> None:
    _run("desktop-assistant", "assistant.py")


def granola_engineer() -> None:
    _run("granola-engineer", "granola_engineer.py")
