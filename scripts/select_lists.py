#!/usr/bin/env python3
"""Select root-level lists for an Actions push or manual build."""

import os
from pathlib import Path
import re
import subprocess


def select_lists(root, before, after="HEAD", manual=False):
    available = sorted(p.name for p in root.glob("*.list") if p.is_file())
    selected = available
    if not manual and re.fullmatch(r"[0-9a-f]{40,64}", before) and set(before) != {"0"}:
        diff = subprocess.run(
            ["git", "diff", "--name-only", "--no-renames", "-z", before, after, "--"],
            cwd=root, capture_output=True, text=True,
        )
        # A new template repository or unavailable pre-force-push commit needs a full build.
        if diff.returncode == 0:
            changed = set(diff.stdout.rstrip("\0").split("\0"))
            rebuild_all = any(
                path in ("Dockerfile", ".no-ghcr", ".no-release") or path.startswith("scripts/")
                or path == ".github/workflows/build.yml" for path in changed
            )
            if not rebuild_all:
                selected = [name for name in available if name in changed]
    for name in selected:
        stem = name[:-5]
        if len(stem) > 64 or not re.fullmatch(r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*", stem):
            raise ValueError("list names must be lowercase Docker image names (1-64 characters): " + name)
        if (root / name).is_symlink():
            raise ValueError("list files must not be symlinks: " + name)
    return selected


def main():
    lists = select_lists(
        Path.cwd(), os.environ.get("BEFORE_SHA", ""), os.environ["GITHUB_SHA"],
        manual=os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch",
    )
    Path(os.environ["LISTS_FILE"]).write_text("".join(name + "\n" for name in lists), encoding="utf-8")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        print("count={}".format(len(lists)), file=output)
        print("ghcr={}".format(str(not Path(".no-ghcr").exists()).lower()), file=output)
        print("release={}".format(str(not Path(".no-release").exists()).lower()), file=output)
    print("Selected: " + (", ".join(lists) if lists else "none"))


if __name__ == "__main__":
    main()
