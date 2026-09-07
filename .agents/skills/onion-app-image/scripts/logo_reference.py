#!/usr/bin/env python3
"""Deterministic Logo selection, prompt, and render-manifest validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
ASSET_MANIFEST = SKILL_DIR / "assets" / "asset-manifest.json"

LOGO_PROMPT_TEMPLATE = (
    "左上角原样呈现{label}的完整 Logo，图形、文字、颜色、比例、轮廓及角标均与原图一致，"
    "不得重绘、变形、简化或拆分；Logo直接融入画面原有背景，周围延续整体色调，"
    "不另加底板、色块、边框或弧形区域，仅调整整体大小和位置。"
)

LOGO_BACKGROUND_CONFLICTS = (
    "Logo区域使用稳定的品牌蓝局部底色",
    "Logo区域使用品牌蓝局部底色",
    "Logo区域采用稳定的品牌蓝局部底色",
    "为Logo单独添加底板",
    "为 Logo 单独添加底板",
    "Logo放在独立色块",
    "Logo置于独立色块",
    "Logo放在弧形区域",
    "Logo置于弧形区域",
)


def logo_prompt_rule(label: str = "参考图1") -> str:
    return LOGO_PROMPT_TEMPLATE.format(label=str(label).strip() or "参考图1")


def load_asset_manifest(path: Path = ASSET_MANIFEST) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assets = data.get("assets")
    if not isinstance(assets, list):
        raise ValueError("asset-manifest.json missing assets list")
    return [asset for asset in assets if isinstance(asset, dict)]


def logo_assets(path: Path = ASSET_MANIFEST) -> list[dict[str, Any]]:
    return [asset for asset in load_asset_manifest(path) if asset.get("kind") == "logo"]


def resolve_logo_selection(
    config: dict[str, Any] | None,
    manifest_path: Path = ASSET_MANIFEST,
) -> dict[str, Any] | None:
    config = config or {}
    name = str(config.get("logo") or config.get("logo_name") or "").strip()
    asset_id = str(config.get("logo_asset_id") or "").strip()
    submitted_path = str(config.get("logo_reference_path") or "").strip()

    if name in {"不用", "不用 Logo", "无", "none", "None"} and not asset_id and not submitted_path:
        return None
    if not name and not asset_id and not submitted_path:
        return None

    assets = logo_assets(manifest_path)
    matches: list[dict[str, Any]] = []
    if asset_id:
        matches = [asset for asset in assets if str(asset.get("asset_id") or "") == asset_id]
        if not matches:
            raise ValueError(f"Logo 资产不存在：{asset_id}")
    elif submitted_path:
        matches = [asset for asset in assets if str(asset.get("path") or "") == submitted_path]
    elif name:
        matches = [asset for asset in assets if str(asset.get("display_name") or "") == name]

    if len(matches) != 1:
        raise ValueError("Logo 选择无法唯一匹配 asset-manifest.json")

    asset = matches[0]
    expected_id = str(asset.get("asset_id") or "")
    expected_path = str(asset.get("path") or "")
    expected_name = str(asset.get("display_name") or "")
    if name and name not in {"不用", "不用 Logo", "无", "none", "None"} and name != expected_name:
        raise ValueError(f"Logo 名称与 asset_id 不匹配：{name} != {expected_name}")
    if submitted_path and submitted_path != expected_path:
        raise ValueError(
            f"Logo asset_id 与 path 不匹配：{expected_id} 应使用 {expected_path}，实际为 {submitted_path}"
        )

    return {
        "logo": expected_name,
        "logo_asset_id": expected_id,
        "logo_reference_path": expected_path,
        "asset": asset,
    }


def canonical_logo_fields(config: dict[str, Any] | None) -> dict[str, str]:
    selection = resolve_logo_selection(config)
    if not selection:
        return {"logo": "不用", "logo_asset_id": "", "logo_reference_path": ""}
    return {
        "logo": selection["logo"],
        "logo_asset_id": selection["logo_asset_id"],
        "logo_reference_path": selection["logo_reference_path"],
    }


def build_logo_reference(config: dict[str, Any], label: str = "参考图1") -> dict[str, Any] | None:
    selection = resolve_logo_selection(config)
    if not selection:
        return None
    asset = selection["asset"]
    return {
        "label": label,
        "role": str(asset.get("prompt_role") or "品牌 Logo 参考图"),
        "asset_id": selection["logo_asset_id"],
        "path": selection["logo_reference_path"],
    }


def validate_asset_reference_bindings(
    reference_items: list[dict[str, Any]],
    manifest_path: Path = ASSET_MANIFEST,
) -> None:
    assets = {str(asset.get("asset_id") or ""): asset for asset in load_asset_manifest(manifest_path)}
    for item in reference_items:
        asset_id = str(item.get("asset_id") or "").strip()
        if not asset_id:
            continue
        asset = assets.get(asset_id)
        if not asset:
            if asset_id.startswith("logo."):
                raise ValueError(f"Logo asset_id 不存在：{asset_id}")
            continue
        expected_path = str(asset.get("path") or "")
        actual_path = str(item.get("path") or "")
        if actual_path != expected_path:
            raise ValueError(
                f"asset_id 与 path 不匹配：{asset_id} 应使用 {expected_path}，实际为 {actual_path}"
            )


def logo_reference_items(
    reference_items: list[dict[str, Any]],
    manifest_path: Path = ASSET_MANIFEST,
) -> list[dict[str, Any]]:
    assets = {str(asset.get("asset_id") or ""): asset for asset in logo_assets(manifest_path)}
    paths = {str(asset.get("path") or "") for asset in assets.values()}
    return [
        item
        for item in reference_items
        if str(item.get("asset_id") or "") in assets or str(item.get("path") or "") in paths
    ]


def validate_logo_prompt_rule(prompt: str, reference_items: list[dict[str, Any]]) -> None:
    for item in logo_reference_items(reference_items):
        label = str(item.get("label") or "参考图1")
        required = logo_prompt_rule(label)
        if required not in prompt:
            raise ValueError(f"prompt 缺少 {label} 的 Logo 保真约束：{required}")
        conflict = next((value for value in LOGO_BACKGROUND_CONFLICTS if value in prompt), None)
        if conflict:
            raise ValueError(f"Logo 背景指令冲突：不得为 Logo 单独添加底板或色块（{conflict}）")


def normalize_job_references(job: dict[str, Any]) -> list[dict[str, Any]]:
    values = job.get("references") or job.get("reference_images") or []
    result = []
    for index, value in enumerate(values, start=1):
        if isinstance(value, dict):
            item = dict(value)
            item.setdefault("label", f"参考图{index}")
            result.append(item)
        else:
            result.append({"label": f"参考图{index}", "path": str(value or "")})
    return result


def validate_manifest_logo(manifest: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    manifest_request = str(manifest.get("request_id") or "").strip()
    config_request = str(config.get("request_id") or "").strip()
    if manifest_request and config_request and manifest_request != config_request:
        raise ValueError(f"request_id 不匹配：manifest={manifest_request}, config={config_request}")

    selection = resolve_logo_selection(config)
    selected_reference = build_logo_reference(config) if selection else None
    for job in manifest.get("jobs") or []:
        slot = int(job.get("slot") or 1)
        if slot > 1:
            continue
        job_id = str(job.get("job_id") or "unknown-job")
        references = normalize_job_references(job)
        validate_asset_reference_bindings(references)
        if not selected_reference:
            if logo_reference_items(references):
                raise ValueError(f"{job_id} 配置为不用 Logo，但 render job 仍传入 Logo")
            continue
        if not references:
            raise ValueError(f"{job_id} 选择了 Logo，但 render job 未传 Logo 参考图")
        first = references[0]
        if first.get("label") != "参考图1":
            raise ValueError(f"{job_id} 的 Logo 必须是参考图1")
        if first.get("asset_id") != selected_reference["asset_id"]:
            raise ValueError(
                f"{job_id} Logo asset_id 与配置不匹配："
                f"{first.get('asset_id')} != {selected_reference['asset_id']}"
            )
        if first.get("path") != selected_reference["path"]:
            raise ValueError(
                f"{job_id} Logo path 与配置不匹配：{first.get('path')} != {selected_reference['path']}"
            )
        validate_logo_prompt_rule(str(job.get("prompt") or ""), [first])
    return selection
