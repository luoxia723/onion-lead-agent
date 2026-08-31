#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request


EXPECTED_MCP_URL = "https://intel-mcp.guanghexinzhi.cn/agent/mcp"


def classify_error_text(value: str) -> str | None:
    text = value.strip().casefold()
    if not text:
        return None
    if any(marker in text for marker in ("github", "raw.githubusercontent.com", "git pull")):
        return "update_check_failed"
    if any(marker in text for marker in ("dependency_timeout", "dataset_changed_restart_pagination", "分页期间")):
        return "business_query_failed"
    if any(
        marker in text
        for marker in (
            "invalid_token",
            "oauth_required",
            "authentication required",
            "refresh token",
            "http 401",
            "status 401",
            "unauthorized",
        )
    ):
        return "oauth_required"
    if any(marker in text for marker in ("管理员安全策略", "browser blocked", "127.0.0.1 callback")):
        return "local_policy_blocked"
    if re.search(r"\b50[0234]\b", text) or any(
        marker in text for marker in ("readyz", "healthz", "service unavailable")
    ):
        return "service_unavailable"
    if any(
        marker in text
        for marker in (
            "connection refused",
            "connection timed out",
            "name resolution",
            "无法连接",
            "443",
        )
    ):
        return "client_network"
    return "task_error"


def probe(url: str, *, timeout: int) -> tuple[int, str]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "onion-role-connection-diagnosis/1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read(4096).decode("utf-8", errors="replace")


def diagnose(*, error_text: str, timeout: int) -> dict[str, object]:
    hinted = classify_error_text(error_text)
    if hinted in {
        "oauth_required",
        "business_query_failed",
        "update_check_failed",
        "local_policy_blocked",
    }:
        return result_for(hinted)
    base = EXPECTED_MCP_URL.removesuffix("/mcp")
    try:
        health_status, _ = probe(base + "/healthz", timeout=timeout)
        ready_status, ready_body = probe(base + "/readyz", timeout=timeout)
    except urllib.error.HTTPError as error:
        if error.code in {401}:
            return result_for("oauth_required")
        if error.code in {403}:
            return result_for("network_or_policy")
        if error.code >= 500:
            return result_for("service_unavailable")
        return result_for("task_error")
    except (OSError, urllib.error.URLError, TimeoutError):
        return result_for("client_network")
    if health_status != 200 or ready_status != 200 or "ready" not in ready_body.casefold():
        return result_for("service_unavailable")
    if hinted:
        return result_for(hinted)
    return result_for("service_ready")


def result_for(category: str) -> dict[str, object]:
    actions = {
        "service_ready": "远程服务正常；如Codex仍报错，保留错误码和request_id继续定位，不要重新填Token。",
        "oauth_required": "仅此状态需要在Codex重新Authenticate，并使用管理员新签发的一次性Token。",
        "business_query_failed": "授权和网络不是根因；保留任务范围、错误码和request_id交给服务维护方。",
        "update_check_failed": "GitHub更新检查失败不影响当前业务；继续使用现有版本，网络恢复后再更新。",
        "local_policy_blocked": "保持Codex运行，允许浏览器访问本机127.0.0.1回调，或联系IT放行。",
        "network_or_policy": "当前出口不在允许网络或被代理策略拦截；连接公司网络或团队代理。",
        "client_network": "本机到公司云不可达；检查网络、DNS和团队代理，不要申请新Token。",
        "service_unavailable": "公司云服务未就绪；停止重复认证，联系服务维护方。",
        "task_error": "服务可达但任务错误未分类；保留原始错误码和request_id交给维护方。",
    }
    return {
        "schema_version": "onion_connection_diagnosis_v1",
        "category": category,
        "token_required": category == "oauth_required",
        "business_can_continue": category in {"service_ready", "update_check_failed"},
        "recommended_action": actions[category],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="区分OAuth、网络、服务、业务查询和更新故障")
    parser.add_argument("--error-text", default="")
    parser.add_argument("--timeout", type=int, default=12)
    args = parser.parse_args()
    payload = diagnose(error_text=args.error_text, timeout=args.timeout)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["business_can_continue"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
