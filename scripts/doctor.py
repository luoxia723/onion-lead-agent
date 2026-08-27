#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


FORBIDDEN_SKILLS = {"onion-intelligence-ingest", "onion-material-ingest", "onion-ai-preroll"}
SECRET_PATTERNS = (
    re.compile(rb"imcp_v1_[A-Za-z0-9_-]{20,}"),
    re.compile(rb"mmcp_v1_[A-Za-z0-9_-]{20,}"),
    re.compile(rb"sk-[A-Za-z0-9_-]{24,}"),
    re.compile(rb"AKLT[A-Za-z0-9]{16,}"),
)
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
USER_DIRECTORIES = ("输入", "产物", "草稿", "审核", "缓存")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查洋葱角色项目仓库")
    parser.add_argument("--offline", action="store_true", help="跳过远程MCP readiness")
    return parser.parse_args()


def project_root() -> Path:
    root = Path(__file__).resolve().parents[1]
    if not (root / "AGENTS.md").is_file():
        raise SystemExit("无法定位角色项目根目录")
    return root


def git_managed_dirty(root: Path) -> list[str]:
    if not (root / ".git").exists():
        return []
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", *MANAGED_PATHS],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def mcp_url(config_text: str) -> str:
    match = re.search(r'^url\s*=\s*"([^"]+)"', config_text, flags=re.MULTILINE)
    if not match:
        raise ValueError("项目配置缺少MCP URL")
    return match.group(1)


def main() -> int:
    args = parse_args()
    root = project_root()
    errors: list[str] = []
    notices: list[str] = []
    role_manifest_path = root / "角色清单.json"
    release_path = root / "发行信息.json"
    if not role_manifest_path.is_file() or not release_path.is_file():
        errors.append("缺少角色清单或发行信息")
    else:
        role = json.loads(role_manifest_path.read_text(encoding="utf-8"))
        release = json.loads(release_path.read_text(encoding="utf-8"))
        expected = set(role.get("resolved_skill_names", []))
        actual = {
            path.parent.name
            for path in (root / ".agents" / "skills").glob("*/SKILL.md")
        }
        if actual != expected:
            errors.append(f"Skill集合不一致：缺少{sorted(expected-actual)}，多出{sorted(actual-expected)}")
        forbidden = actual & FORBIDDEN_SKILLS
        if forbidden:
            errors.append("包含禁止发行Skill：" + ", ".join(sorted(forbidden)))
        if release.get("role") != role.get("role"):
            errors.append("角色清单与发行信息不一致")
        if release.get("skill_discovery_root") != ".agents/skills":
            errors.append("Skill发现根目录不是.agents/skills")
        if release.get("mcp_connection_status") != "deployed":
            notices.append("统一OAuth MCP尚未部署；当前仅为结构验收快照")

    for name in USER_DIRECTORIES:
        directory = root / "工作区" / name
        if not directory.is_dir():
            errors.append(f"缺少用户目录：工作区/{name}")
    dirty = git_managed_dirty(root)
    if dirty:
        errors.append("系统维护区存在本地修改：" + " | ".join(dirty))

    for relative in MANAGED_PATHS:
        managed = root / relative
        candidates = [managed] if managed.is_file() else managed.rglob("*") if managed.is_dir() else []
        for path in candidates:
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                continue
            data = path.read_bytes()
            if any(pattern.search(data) for pattern in SECRET_PATTERNS):
                errors.append(f"系统维护区疑似包含真实密钥：{path.relative_to(root)}")

    if not args.offline:
        config_path = root / ".codex" / "config.toml"
        try:
            url = mcp_url(config_path.read_text(encoding="utf-8"))
            ready_url = url.removesuffix("/mcp") + "/readyz"
            with urllib.request.urlopen(ready_url, timeout=12) as response:
                if response.status != 200:
                    errors.append(f"MCP readiness返回HTTP {response.status}")
        except (OSError, ValueError, urllib.error.URLError, TimeoutError) as error:
            errors.append(f"无法连接统一OAuth MCP：{error}")

    for notice in notices:
        print(f"NOTICE: {notice}")
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors))
        return 1
    print("role_workspace_doctor=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
