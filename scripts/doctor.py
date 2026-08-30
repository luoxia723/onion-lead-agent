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
    "首次使用.md",
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
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", *MANAGED_PATHS],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        return ["Git未安装，无法检查系统维护区"]
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
        role_workflow_hash = str(role.get("workflow_contract_sha256") or "")
        release_workflow_hash = str(release.get("workflow_contract_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", role_workflow_hash):
            errors.append("角色清单缺少有效工作流合同哈希")
        if role_workflow_hash != release_workflow_hash:
            errors.append("角色清单与发行信息的工作流合同哈希不一致")
        role_artifact_hash = str(role.get("artifact_contract_sha256") or "")
        release_artifact_hash = str(release.get("artifact_contract_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", role_artifact_hash):
            errors.append("角色清单缺少有效产物目录合同哈希")
        if role_artifact_hash != release_artifact_hash:
            errors.append("角色清单与发行信息的产物目录合同哈希不一致")
        agents_text = (root / "AGENTS.md").read_text(encoding="utf-8")
        if "## Skill 路由与上下文" not in agents_text:
            errors.append("AGENTS缺少Skill路由与上下文")
        for skill_name in expected:
            if agents_text.count(f"| `{skill_name}` |") != 1:
                errors.append(f"AGENTS路由不是唯一一条：{skill_name}")
        if "不因角色拥有多个Skill而预加载全部Skill" not in agents_text:
            errors.append("AGENTS缺少最小上下文规则")
        if "`onion-ai-preroll`当前暂缓且尚未进入本角色发行" not in agents_text:
            errors.append("AGENTS缺少未发行AI前贴边界")

        stale_phrases = ("统一MCP服务器的ffmpeg", "无字幕本地渲染", "服务器的ffmpeg")
        for path in (root / ".agents" / "skills").rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            if any(phrase in text for phrase in stale_phrases):
                errors.append(f"Skill残留已替代执行口径：{path.relative_to(root)}")

    for name in USER_DIRECTORIES:
        directory = root / "工作区" / name
        if not directory.is_dir():
            errors.append(f"缺少用户目录：工作区/{name}")
    if not (root / "首次使用.md").is_file():
        errors.append("缺少包内首次使用说明")
    if not (root / "scripts" / "first_run_check.py").is_file():
        errors.append("缺少首次环境检查脚本")
    if not (root / "scripts" / "artifact_workspace.py").is_file():
        errors.append("缺少统一产物目录脚本")
    if not (root / "scripts" / "workspace_contract.py").is_file():
        errors.append("缺少角色工作区机器合同")
    if not (root / ".agents" / "references" / "artifact-layout.json").is_file():
        errors.append("缺少统一产物目录合同")
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
