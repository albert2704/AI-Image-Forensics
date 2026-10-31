"""Turn report image paths into repo-relative Markdown links.

Frozen verification records store absolute paths from the machine that produced
them. A generated Markdown file must not repeat those paths, and a link to a
file that is not in the repository is worse than a caption.
"""

from __future__ import annotations

from pathlib import Path

MARKERS = ("output", "docs", "data", "external")


def repo_relative(path, root):
    """Return the path relative to root, or None when it does not resolve to a repo file."""
    root = Path(root).resolve()
    candidate = Path(path)
    try:
        relative = candidate.resolve().relative_to(root)
    except (ValueError, OSError):
        relative = None
    if relative is not None and (root / relative).is_file():
        return relative
    parts = candidate.parts
    for marker in MARKERS:
        if marker not in parts:
            continue
        index = len(parts) - 1 - parts[::-1].index(marker)
        salvaged = root.joinpath(*parts[index:])
        if salvaged.is_file():
            return salvaged.relative_to(root)
    return None


def markdown_image(label, path, root):
    """Emit a relative Markdown image, or a caption when the file is not in the repository."""
    relative = repo_relative(path, root)
    return f"![{label}](../{relative})\n" if relative else f"*{label}: artifact not in this repository.*\n"
