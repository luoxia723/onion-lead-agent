#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path


MANAGED_PATHS = (
    "AGENTS.md",
    "README.md",
    ".agents",
    "产品资料",
    ".codex",
    "scripts",
    "VERSION",
    "发行信息.json",
    "角色清单.json",
    ".gitignore",
    "工作区/README.md",
)
USER_ROOTS = (
    "工作区/输入",
    "工作区/产物",
    "工作区/草稿",
    "工作区/审核",
    "工作区/缓存",
    ".runtime",
)


def run(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=check
    )


def file_hashes(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in USER_ROOTS:
        directory = root / relative
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.name == ".gitkeep":
                continue
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    if not (root / ".git").exists():
        raise SystemExit("当前目录不是Git角色仓库")
    dirty = run(root, "status", "--porcelain", "--", *MANAGED_PATHS).stdout.strip()
    if dirty:
        print("系统维护区存在本地修改，已停止更新：")
        print(dirty)
        return 2
    before = file_hashes(root)
    run(root, "fetch", "--prune", "origin", "main")
    ancestor = run(root, "merge-base", "--is-ancestor", "HEAD", "origin/main", check=False)
    if ancestor.returncode != 0:
        print("本地分支与origin/main发生分叉，已停止；不会reset或覆盖。")
        return 3
    run(root, "merge", "--ff-only", "origin/main")
    after = file_hashes(root)
    if before != after:
        print("用户工作区文件在更新中发生变化，更新合同失败。")
        return 4
    doctor = subprocess.run(
        [sys.executable, str(root / "scripts" / "doctor.py"), "--offline"],
        cwd=root,
    )
    if doctor.returncode != 0:
        return doctor.returncode
    print("workspace_update=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
