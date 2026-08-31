#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from codex_runtime import resolve_codex_binary
from sync_role_dependencies import dependency_status


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


EXPECTED_MCP_URL = "https://intel-mcp.guanghexinzhi.cn/agent/mcp"
PROXY_KEYS = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="首次使用前检查 Codex 角色项目")
    parser.add_argument("--offline", action="store_true", help="跳过远程MCP健康检查")
    parser.add_argument("--json", action="store_true", help="以JSON输出结果")
    return parser.parse_args()


def project_root() -> Path:
    root = Path(__file__).resolve().parents[1]
    if not (root / "角色清单.json").is_file():
        raise SystemExit("无法定位角色项目根目录")
    return root


def add(results: list[dict[str, str]], name: str, status: str, detail: str) -> None:
    results.append({"name": name, "status": status, "detail": detail})


def fetch_status(url: str) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "onion-role-first-run-check/1"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.status, response.read(4096).decode("utf-8", errors="replace")


def main() -> int:
    args = parse_args()
    root = project_root()
    results: list[dict[str, str]] = []
    role = json.loads((root / "角色清单.json").read_text(encoding="utf-8"))
    role_name = str(role.get("role") or "")

    version_ok = sys.version_info >= (3, 10)
    add(
        results,
        "Python",
        "ok" if version_ok else "error",
        f"{platform.python_version()} ({platform.system()} {platform.machine()})",
    )
    runtime_venv = root / ".runtime" / "venv"
    using_project_venv = Path(sys.prefix).resolve() == runtime_venv.resolve()
    add(
        results,
        "项目Python环境",
        "ok" if using_project_venv else "warn",
        "正在使用项目.runtime/venv"
        if using_project_venv
        else "当前Python可用；建议让Codex运行“初始化项目环境”建立隔离venv",
    )

    git_path = shutil.which("git")
    git_required = (root / ".git").is_dir()
    add(
        results,
        "Git",
        "ok" if git_path else "error" if git_required else "warn",
        git_path or "未在PATH中找到；ZIP可使用，Git仓库Pull需要安装Git",
    )
    add(results, "Git仓库", "ok" if (root / ".git").is_dir() else "warn", "可以Git拉取更新" if (root / ".git").is_dir() else "当前是ZIP目录；可正常试用，但不能直接Pull")

    codex_path = resolve_codex_binary(required=False)
    codex_needed = role_name == "strategy"
    add(
        results,
        "Codex执行器",
        "ok" if codex_path else "warn" if codex_needed else "ok",
        str(codex_path)
        if codex_path
        else "策略报告的隔离模型任务需要；APP/线索日常任务不依赖Codex CLI",
    )
    add(results, "Node.js", "ok", "正式角色流程不需要安装")
    add(results, "FFmpeg", "ok", "正式视频由统一MCP的火山VOD云端渲染，本地不需要安装")
    package_required, package_ok, package_detail = dependency_status(root)
    add(
        results,
        "本地Python包",
        "ok" if package_ok else "error",
        package_detail if package_required else "当前角色只使用Python标准库",
    )

    required = (
        "AGENTS.md",
        "README.md",
        "首次使用.md",
        ".codex/config.toml",
        "角色清单.json",
        "发行信息.json",
        "产品资料/产品事实与卖点.md",
        "产品资料/当前渠道投放口径.md",
        "scripts/doctor.py",
        "scripts/diagnose_connection.py",
        "scripts/update_workspace.py",
        "scripts/workspace_contract.py",
    )
    missing = [relative for relative in required if not (root / relative).is_file()]
    add(results, "项目文件", "error" if missing else "ok", "缺少：" + "、".join(missing) if missing else "首次使用、更新和产品事实文件齐全")

    expected = set(role.get("resolved_skill_names", []))
    actual = {path.parent.name for path in (root / ".agents" / "skills").glob("*/SKILL.md")}
    skill_ok = actual == expected and bool(actual)
    detail = f"角色={role.get('role')}，Skill={len(actual)}个"
    if actual != expected:
        detail += f"，缺少={sorted(expected - actual)}，多出={sorted(actual - expected)}"
    add(results, "Skills", "ok" if skill_ok else "error", detail)

    syntax_errors: list[str] = []
    for base in (root / "scripts", root / ".agents"):
        for path in base.rglob("*.py"):
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, SyntaxError) as error:
                syntax_errors.append(f"{path.relative_to(root)}:{error}")
    add(
        results,
        "Python脚本语法",
        "error" if syntax_errors else "ok",
        "；".join(syntax_errors[:3]) if syntax_errors else "全部可由当前Python解析",
    )

    symlinks = [str(path.relative_to(root)) for path in (root / ".agents").rglob("*") if path.is_symlink()]
    add(results, "Windows/macOS目录兼容", "error" if symlinks else "ok", "未使用符号链接" if not symlinks else "发现符号链接：" + "、".join(symlinks[:5]))

    config_path = root / ".codex" / "config.toml"
    config_text = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    url_match = re.search(r'^url\s*=\s*"([^"]+)"', config_text, flags=re.MULTILINE)
    configured_url = url_match.group(1) if url_match else ""
    config_ok = configured_url == EXPECTED_MCP_URL and "bearer_token_env_var" not in config_text
    add(results, "MCP项目配置", "ok" if config_ok else "error", configured_url or "未找到onion-agent URL")

    proxy_configured = any(os.environ.get(key) for key in PROXY_KEYS)
    add(results, "系统代理", "ok" if proxy_configured else "warn", "已检测到代理环境（不显示具体值）" if proxy_configured else "未检测到命令行代理；公司网络内或桌面端代理正常时可忽略")

    doctor = subprocess.run(
        [sys.executable, str(root / "scripts" / "doctor.py"), "--offline"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    doctor_detail = (doctor.stdout + doctor.stderr).strip().replace("\n", " | ")
    add(results, "仓库完整性", "ok" if doctor.returncode == 0 else "error", doctor_detail or f"退出码={doctor.returncode}")

    if args.offline:
        add(results, "MCP远程服务", "skip", "已按--offline跳过")
    elif configured_url:
        base_url = configured_url.removesuffix("/mcp")
        try:
            health_status, _ = fetch_status(base_url + "/healthz")
            ready_status, ready_body = fetch_status(base_url + "/readyz")
            ready_ok = health_status == 200 and ready_status == 200 and "ready" in ready_body.lower()
            add(results, "MCP远程服务", "ok" if ready_ok else "error", f"healthz={health_status}，readyz={ready_status}")
        except (OSError, urllib.error.URLError, TimeoutError) as error:
            add(results, "MCP远程服务", "error", f"无法连接：{error}")

    error_count = sum(item["status"] == "error" for item in results)
    warn_count = sum(item["status"] == "warn" for item in results)
    payload = {
        "ok": error_count == 0,
        "role": role_name,
        "skill_count": len(actual),
        "error_count": error_count,
        "warning_count": warn_count,
        "checks": results,
        "next_steps": [
            "在Codex中打开该仓库根目录并信任项目",
            "打开设置 > MCP servers，对onion-agent点击Authenticate",
            "在浏览器认证页输入管理员单独发放的一次性Token",
            "返回Codex用/mcp确认连接，用/skills确认Skill已加载",
        ],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"首次环境检查：{'PASS' if payload['ok'] else 'FAIL'}")
        for item in results:
            print(f"[{item['status'].upper():5}] {item['name']}: {item['detail']}")
        print("\n下一步：")
        for index, step in enumerate(payload["next_steps"], start=1):
            print(f"{index}. {step}")
        print("\n注意：此检查不读取、不保存、不输出激活Token或OAuth凭据。")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
