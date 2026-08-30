#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


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
UPDATE_STATUS_RELATIVE = Path(".runtime") / "update-status.json"
CHECK_TTL_SECONDS = 24 * 60 * 60


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def version(root: Path, ref: str | None = None) -> str:
    if ref is None:
        path = root / "VERSION"
        return path.read_text(encoding="utf-8").strip() if path.is_file() else "unknown"
    result = run(root, "show", f"{ref}:VERSION", check=False)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else "unknown"


def cached_check(root: Path, workspace_identity: str) -> dict[str, object] | None:
    cached = load_json(root / UPDATE_STATUS_RELATIVE)
    if not cached or cached.get("workspace_identity") != workspace_identity:
        return None
    try:
        checked_epoch = float(cached.get("checked_epoch") or 0)
        defer_until_epoch = float(cached.get("defer_until_epoch") or 0)
    except (TypeError, ValueError):
        return None
    if time.time() - checked_epoch >= CHECK_TTL_SECONDS:
        return None
    result = dict(cached)
    if result.get("update_available"):
        result["status"] = "deferred" if defer_until_epoch > time.time() else "update_available"
    result["cached"] = True
    return result


def zip_identity(root: Path) -> str:
    release = load_json(root / "发行信息.json") or {}
    revision = str(release.get("source_revision") or "unknown")
    return f"zip:{version(root)}:{revision}"


def remote_version_url(root: Path) -> str:
    repository = repository_name(root)
    return f"https://raw.githubusercontent.com/{PUBLIC_OWNER}/{repository}/main/VERSION"


def zip_remote_version(root: Path, repository_url: str | None) -> str:
    if repository_url:
        with tempfile.TemporaryDirectory(prefix="onion-role-check-") as raw:
            snapshot = Path(raw) / "snapshot"
            clone = subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    "main",
                    "--single-branch",
                    repository_url,
                    str(snapshot),
                ],
                capture_output=True,
                text=True,
            )
            if clone.returncode != 0:
                raise RuntimeError(clone.stderr.strip() or "无法检查远端版本")
            validate_snapshot(snapshot, repository_name(root))
            return version(snapshot)
    with urlopen(remote_version_url(root), timeout=15) as response:
        if response.status != 200:
            raise RuntimeError(f"版本检查返回HTTP {response.status}")
        value = response.read(128).decode("utf-8").strip()
    if not value:
        raise RuntimeError("远端版本为空")
    return value


def update_check(root: Path, repository_url: str | None = None) -> dict[str, object]:
    now = utc_now()
    if not (root / ".git").is_dir():
        identity = zip_identity(root)
        if cached := cached_check(root, identity):
            return cached
        local_version = version(root)
        try:
            remote_version = zip_remote_version(root, repository_url)
            available = local_version != remote_version
            result = {
                "schema_version": "onion_role_update_status_v1",
                "status": "update_available" if available else "current",
                "update_available": available,
                "can_apply": available,
                "install_type": "zip",
                "checked_at": isoformat(now),
                "checked_epoch": now.timestamp(),
                "local_version": local_version,
                "remote_version": remote_version,
                "workspace_identity": identity,
                "defer_until": None,
                "defer_until_epoch": None,
                "cached": False,
            }
        except (OSError, RuntimeError, subprocess.SubprocessError, URLError) as error:
            result = {
                "schema_version": "onion_role_update_status_v1",
                "status": "check_failed",
                "update_available": False,
                "install_type": "zip",
                "checked_at": isoformat(now),
                "checked_epoch": now.timestamp(),
                "local_version": local_version,
                "remote_version": None,
                "workspace_identity": identity,
                "error": str(error),
                "cached": False,
            }
        write_json(root / UPDATE_STATUS_RELATIVE, result)
        return result

    local_commit = "unknown"
    identity = f"git:{version(root)}"
    try:
        local_commit = run(root, "rev-parse", "HEAD").stdout.strip()
        identity = f"git:{local_commit}"
        if cached := cached_check(root, identity):
            return cached
        run(root, "fetch", "--prune", "origin", "main")
        remote_commit = run(root, "rev-parse", "origin/main").stdout.strip()
        if local_commit == remote_commit:
            status = "current"
        elif run(
            root, "merge-base", "--is-ancestor", local_commit, remote_commit, check=False
        ).returncode == 0:
            status = "update_available"
        elif run(
            root, "merge-base", "--is-ancestor", remote_commit, local_commit, check=False
        ).returncode == 0:
            status = "local_ahead"
        else:
            status = "diverged"
        dirty = bool(run(root, "status", "--porcelain", "--", *MANAGED_PATHS).stdout.strip())
        result = {
            "schema_version": "onion_role_update_status_v1",
            "status": status,
            "update_available": status == "update_available",
            "can_apply": status == "update_available" and not dirty,
            "checked_at": isoformat(now),
            "checked_epoch": now.timestamp(),
            "local_version": version(root),
            "remote_version": version(root, "origin/main"),
            "workspace_identity": identity,
            "local_commit": local_commit,
            "remote_commit": remote_commit,
            "managed_paths_dirty": dirty,
            "defer_until": None,
            "defer_until_epoch": None,
            "cached": False,
        }
    except (OSError, subprocess.SubprocessError) as error:
        result = {
            "schema_version": "onion_role_update_status_v1",
            "status": "check_failed",
            "update_available": False,
            "checked_at": isoformat(now),
            "checked_epoch": now.timestamp(),
            "local_version": version(root),
            "workspace_identity": identity,
            "local_commit": local_commit,
            "error": str(error),
            "cached": False,
        }
    write_json(root / UPDATE_STATUS_RELATIVE, result)
    return result


def snooze_update(root: Path, hours: int, repository_url: str | None = None) -> dict[str, object]:
    if hours <= 0:
        raise SystemExit("--snooze-hours必须大于0")
    current = update_check(root, repository_url)
    if not current.get("update_available") and current.get("status") != "deferred":
        return current
    deferred = dict(current)
    until = utc_now() + timedelta(hours=hours)
    deferred.update(
        {
            "status": "deferred",
            "defer_until": isoformat(until),
            "defer_until_epoch": until.timestamp(),
            "cached": False,
        }
    )
    write_json(root / UPDATE_STATUS_RELATIVE, deferred)
    return deferred


def record_current(root: Path) -> None:
    if not (root / ".git").is_dir():
        return
    now = utc_now()
    commit = run(root, "rev-parse", "HEAD").stdout.strip()
    write_json(
        root / UPDATE_STATUS_RELATIVE,
        {
            "schema_version": "onion_role_update_status_v1",
            "status": "current",
            "update_available": False,
            "can_apply": False,
            "checked_at": isoformat(now),
            "checked_epoch": now.timestamp(),
            "local_version": version(root),
            "remote_version": version(root),
            "workspace_identity": f"git:{commit}",
            "local_commit": commit,
            "remote_commit": commit,
            "managed_paths_dirty": False,
            "defer_until": None,
            "defer_until_epoch": None,
            "cached": False,
        },
    )


def project_python(root: Path) -> Path | None:
    candidates = (
        root / ".runtime" / "venv" / "bin" / "python",
        root / ".runtime" / "venv" / "Scripts" / "python.exe",
    )
    return next((path for path in candidates if path.is_file()), None)


def sync_dependencies(root: Path) -> int:
    requirement = root / ".agents" / "skills" / "onion-app-image" / "requirements.txt"
    if not requirement.is_file():
        return 0
    python = project_python(root)
    if python is None:
        print("更新已完成，但APP图片本地依赖尚未同步；请运行项目环境初始化。")
        return 0
    result = subprocess.run(
        [str(python), str(root / "scripts" / "sync_role_dependencies.py"), "--install"],
        cwd=root,
    )
    return result.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="安全更新Codex角色项目")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--adopt-git",
        action="store_true",
        help="把现有ZIP工作目录一次性接入对应公开GitHub仓库",
    )
    actions.add_argument(
        "--check", action="store_true", help="只读检查更新；24小时内复用缓存"
    )
    actions.add_argument(
        "--apply", action="store_true", help="用户确认后安全快进更新；默认行为"
    )
    actions.add_argument("--snooze-hours", type=int, help="暂缓更新提示指定小时数")
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
            if path.resolve() == (root / UPDATE_STATUS_RELATIVE).resolve():
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
    record_current(root)
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
    dependency_result = sync_dependencies(root)
    if dependency_result != 0:
        return dependency_result
    record_current(root)
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
    if args.check:
        print(json.dumps(update_check(root, args.repository_url), ensure_ascii=False))
        return 0
    if args.snooze_hours is not None:
        print(
            json.dumps(
                snooze_update(root, args.snooze_hours, args.repository_url),
                ensure_ascii=False,
            )
        )
        return 0
    if not (root / ".git").is_dir():
        return adopt_git(root, args.repository_url)
    return update_git(root)


if __name__ == "__main__":
    raise SystemExit(main())
