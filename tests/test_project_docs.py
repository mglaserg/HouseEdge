from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DOCS = (
    "AGENTS.md",
    "PROJECT_STATUS.md",
    "ROADMAP.md",
    "docs/ARCHITECTURE.md",
    "docs/DEVELOPMENT.md",
    "docs/adr/README.md",
    "docs/adr/0001-separate-calibration-from-primary-outcome.md",
)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def test_canonical_project_docs_exist_and_local_links_resolve():
    missing_docs = [path for path in CANONICAL_DOCS if not (ROOT / path).is_file()]
    assert not missing_docs

    broken_links = []
    for relative_path in ("README.md", *CANONICAL_DOCS):
        document = ROOT / relative_path
        for match in MARKDOWN_LINK.finditer(document.read_text(encoding="utf-8")):
            target = match.group(1).split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            if not (document.parent / target).exists():
                broken_links.append(f"{relative_path} -> {target}")

    assert not broken_links
