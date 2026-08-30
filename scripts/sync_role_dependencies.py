#!/usr/bin/env python3
"""Check or install the small, role-specific local Python dependency set."""

from __future__ import annotations

import argparse
from importlib import metadata
from pathlib import Path
import re
import subprocess
import sys


PIN = re.compile(r"^Pillow==([0-9]+(?:\.[0-9]+){2})$")


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def pillow_requirement(root: Path) -> tuple[Path, str] | None:
    path = root / ".agents" / "skills" / "onion-app-image" / "requirements.txt"
    if not path.is_file():
        return None
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if len(lines) != 1 or not (match := PIN.fullmatch(lines[0])):
        raise ValueError(f"APP图片依赖必须精确锁定一个Pillow版本：{path}")
    return path, match.group(1)


def dependency_status(root: Path) -> tuple[bool, bool, str]:
    requirement = pillow_requirement(root)
    if requirement is None:
        return False, True, "当前角色不包含APP图片Skill，无额外Python包"
    _, expected = requirement
    try:
        actual = metadata.version("Pillow")
    except metadata.PackageNotFoundError:
        return True, False, f"缺少Pillow=={expected}"
    if actual != expected:
        return True, False, f"Pillow版本不匹配：当前{actual}，需要{expected}"
    return True, True, f"Pillow=={actual}"


def install(root: Path) -> None:
    requirement = pillow_requirement(root)
    if requirement is None:
        return
    path, _ = requirement
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-r", str(path)],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    root = project_root()
    _, ready, _ = dependency_status(root)
    if args.install and not ready:
        install(root)
    required, ok, detail = dependency_status(root)
    print(f"role_dependencies={'ok' if ok else 'missing'} required={str(required).lower()} detail={detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
