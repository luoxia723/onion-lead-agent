#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


PUBLIC_OWNER = "luoxia723"
PUBLIC_REPOSITORIES = {
    "onion-strategy-agent",
    "onion-app-agent",
    "onion-lead-agent",
}
MANAGED_PATHS = (
    "AGENTS.md",
    "README.md",
    "首次使用.md",
    "连接Agent.command",
    "连接Agent.cmd",
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
USER_MARKERS = tuple(f"{path}/.gitkeep" for path in USER_ROOTS)
BACKUP_RELATIVE = Path(".runtime") / "system-backups"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="安全更新Codex角色项目")
    parser.add_argument(
        "--adopt-git",
        action="store_true",
        help="把现有ZIP工作目录一次性接入对应公开GitHub仓库",
    )
    parser.add_argument("--project-root", type=Path)
    parser.add_argument(
        "--repository-url",
        help="覆盖自动推导的仓库地址；主要用于隔离验收",
    )
    return parser.parse_args()


def run(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=check
    )


def file_hashes(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    backup_root = (root / BACKUP_RELATIVE).resolve()
    for relative in USER_ROOTS:
        directory = root / relative
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.name == ".gitkeep":
                continue
            try:
                path.resolve().relative_to(backup_root)
                continue
            except ValueError:
                pass
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def remove_entry(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def copy_entry(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)


def repository_name(root: Path) -> str:
    release_path = root / "发行信息.json"
    if not release_path.is_file():
        raise SystemExit("当前目录缺少发行信息.json，不能识别角色仓库")
    release = json.loads(release_path.read_text(encoding="utf-8"))
    repository = str(release.get("repository") or "")
    if repository not in PUBLIC_REPOSITORIES:
        raise SystemExit(f"不是允许接入的角色仓库：{repository or 'unknown'}")
    return repository


def default_repository_url(root: Path) -> str:
    return f"https://github.com/{PUBLIC_OWNER}/{repository_name(root)}.git"


def validate_snapshot(snapshot: Path, expected_repository: str) -> None:
    release = json.loads((snapshot / "发行信息.json").read_text(encoding="utf-8"))
    if release.get("repository") != expected_repository:
        raise SystemExit("远端仓库角色与当前工作目录不一致")
    required = (
        "AGENTS.md",
        ".codex/config.toml",
        "scripts/update_workspace.py",
        "角色清单.json",
    )
    missing = [relative for relative in required if not (snapshot / relative).is_file()]
    if missing:
        raise SystemExit("远端角色仓库缺少必要文件：" + "、".join(missing))


def install_snapshot(root: Path, snapshot: Path, backup: Path) -> None:
    for relative in MANAGED_PATHS:
        source = snapshot / relative
        target = root / relative
        if target.exists() or target.is_symlink():
            copy_entry(target, backup / relative)
            remove_entry(target)
        if source.exists():
            copy_entry(source, target)
    for relative in USER_MARKERS:
        source = snapshot / relative
        target = root / relative
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    shutil.copytree(snapshot / ".git", root / ".git")


def rollback_snapshot(root: Path, backup: Path) -> None:
    remove_entry(root / ".git") if (root / ".git").exists() else None
    for relative in MANAGED_PATHS:
        target = root / relative
        if target.exists() or target.is_symlink():
            remove_entry(target)
        saved = backup / relative
        if saved.exists() or saved.is_symlink():
            copy_entry(saved, target)


def adopt_git(root: Path, repository_url: str | None) -> int:
    if (root / ".git").exists():
        print("当前目录已经接入Git，继续执行普通更新。")
        return update_git(root)
    if not shutil.which("git"):
        raise SystemExit("缺少Git，无法接入自动更新；请先安装Git")
    repository = repository_name(root)
    url = repository_url or default_repository_url(root)
    before = file_hashes(root)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = root / BACKUP_RELATIVE / stamp
    backup.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="onion-role-adopt-") as raw:
        snapshot = Path(raw) / repository
        clone = subprocess.run(
            ["git", "clone", "--branch", "main", "--single-branch", url, str(snapshot)],
            capture_output=True,
            text=True,
        )
        if clone.returncode != 0:
            raise SystemExit("无法下载公开角色仓库：" + clone.stderr.strip())
        validate_snapshot(snapshot, repository)
        try:
            install_snapshot(root, snapshot, backup)
            dirty = run(
                root,
                "status",
                "--porcelain",
                "--",
                *MANAGED_PATHS,
                *USER_MARKERS,
            ).stdout.strip()
            if dirty:
                raise RuntimeError("接入后系统维护区不干净：\n" + dirty)
            if file_hashes(root) != before:
                raise RuntimeError("接入过程中用户工作区发生变化")
            doctor = subprocess.run(
                [sys.executable, str(root / "scripts" / "doctor.py"), "--offline"],
                cwd=root,
            )
            if doctor.returncode != 0:
                raise RuntimeError("接入后仓库完整性检查失败")
        except Exception as error:
            rollback_snapshot(root, backup)
            if file_hashes(root) != before:
                raise SystemExit("接入失败且用户文件校验异常，请保留现场联系管理员")
            raise SystemExit(f"接入失败，系统文件已恢复：{error}") from error
    print(f"workspace_adopt=ok repository={repository} branch=main")
    print(f"system_backup={backup}")
    print("以后对Codex说“更新项目到最新”即可，不需要重新下载ZIP。")
    return 0


def update_git(root: Path) -> int:
    if not (root / ".git").exists():
        print("当前是ZIP工作目录，尚未接入自动更新。")
        print("请运行：python scripts/update_workspace.py --adopt-git")
        return 5
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
    if before != file_hashes(root):
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


def main() -> int:
    args = parse_args()
    root = (
        args.project_root.expanduser().resolve()
        if args.project_root
        else Path(__file__).resolve().parents[1]
    )
    if args.adopt_git:
        return adopt_git(root, args.repository_url)
    return update_git(root)


if __name__ == "__main__":
    raise SystemExit(main())
