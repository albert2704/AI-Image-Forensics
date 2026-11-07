"""Turn report image paths into repo-relative Markdown links.

Frozen verification records store absolute paths from the machine that produced
them. A generated Markdown file must not repeat those paths, and a link to a
file that is not in the repository is worse than a caption.
"""

from __future__ import annotations

from pathlib import Path

MARKERS = ("output", "docs", "data", "external")
IGNORED_ROOTS = (Path("external"), Path("output/runs"), Path("data/benchmark/images"),
                 Path("weights"), Path(".venv"), Path("tmp"))


def _ignored(relative):
    """Mirror the directory entries in .gitignore. A file there is absent from a clone."""
    return any(relative == root or root in relative.parents for root in IGNORED_ROOTS)


def _kept(relative, root):
    return relative is not None and not _ignored(relative) and (root / relative).is_file()


def repo_relative(path, root):
    """Return the path relative to root, or None when it does not resolve to a repository file."""
    root = Path(root).resolve()
    candidate = Path(path)
    try:
        relative = candidate.resolve().relative_to(root)
    except (ValueError, OSError):
        relative = None
    if _kept(relative, root):
        return relative
    parts = candidate.parts
    for marker in MARKERS:
        if marker not in parts:
            continue
        index = len(parts) - 1 - parts[::-1].index(marker)
        try:
            relative = root.joinpath(*parts[index:]).resolve().relative_to(root)
        except (ValueError, OSError):
            continue
        if _kept(relative, root):
            return relative
    return None


def markdown_image(label, path, root):
    """Emit a relative Markdown image, or a caption when the file is not in the repository."""
    relative = repo_relative(path, root)
    return f"![{label}](../{relative})\n" if relative else f"*{label}: artifact not in this repository.*\n"
