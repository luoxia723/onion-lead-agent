#!/usr/bin/env python3
"""
Local interaction server for onion-app-image.

This is the half-automatic bridge for Codex/Claude runtimes that cannot show a
native choice card. It serves a deterministic image configuration page, writes
the submitted result to JSON, and can also serve generated selection pages and
their local image assets from the same output directory.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import posixpath
import socket
import sys
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from zoneinfo import ZoneInfo


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_CHANNEL_RULES = SKILL_DIR / "config" / "channel-placement-rules.json"
ASSET_MANIFEST = SKILL_DIR / "assets" / "asset-manifest.json"
CONFIG_TEMPLATE = SKILL_DIR / "templates" / "image-config.html"
FONT_DIR = SKILL_DIR / "assets" / "font-references"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from build_selection_page import normalize_sets  # noqa: E402
from logo_reference import canonical_logo_fields  # noqa: E402

IMAGE_SETS_FILE = "image-sets.json"
MAX_BATCH_GROUP_COUNT = 100


def repository_root(start: Path = SKILL_DIR) -> Path:
    current = start.resolve()
    while True:
        if (current / "AGENTS.md").is_file() and (
            (current / "Skills").is_dir()
            or (current / ".agents" / "skills").is_dir()
        ):
            return current
        if current.parent == current:
            raise RuntimeError("cannot locate repository root")
        current = current.parent


def runtime_output_root() -> Path:
    return repository_root() / ".runtime" / "策略Agent产物"


def request_output_dir(request_id: str) -> Path:
    """Return the creation-date image task directory used by the documented contract."""
    safe_id = "".join(char if char.isalnum() or char in "-_." else "-" for char in str(request_id))
    safe_id = safe_id.strip("-.") or "image-request"
    created = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y年%m月%d日")
    return runtime_output_root() / created / "APP图片" / safe_id


def resolve_output_dir(value: str | None, request_id: str) -> Path:
    output = (
        Path(value).expanduser().resolve()
        if value
        else request_output_dir(request_id).resolve()
    )
    repository = repository_root()
    allowed_roots = (
        runtime_output_root().resolve(),
        (repository / "工作区" / "产物").resolve(),
    )
    if not any(output == root or root in output.parents for root in allowed_roots):
        raise ValueError(
            "output directory must stay under .runtime/策略Agent产物 or 工作区/产物"
        )
    return output


FALLBACK_SLOTS = [
    {
        "id": "oppo_app_store_single_16_9_big",
        "platform": "OPPO",
        "name": "富媒体 - 横版大图",
        "channel": "应用商店",
        "imageForm": "单图",
        "ratio": "16:9",
        "width": 1280,
        "height": 720,
        "maxFileSizeKb": 150,
        "notes": "可加 Logo",
    },
    {
        "id": "oppo_app_store_double_9_16",
        "platform": "OPPO",
        "name": "富媒体 - 横版两图",
        "channel": "应用商店",
        "imageForm": "双图",
        "ratio": "9:16",
        "width": 474,
        "height": 768,
        "maxFileSizeKb": 150,
    },
    {
        "id": "oppo_app_store_triple_3_2",
        "platform": "OPPO",
        "name": "富媒体 - 横版三图",
        "channel": "应用商店",
        "imageForm": "三图",
        "ratio": "3:2",
        "width": 320,
        "height": 210,
        "maxFileSizeKb": 100,
    },
    {
        "id": "oppo_app_store_single_16_9_banner",
        "platform": "OPPO",
        "name": "竞价 banner",
        "channel": "应用商店",
        "imageForm": "单图",
        "ratio": "16:9",
        "width": 1280,
        "height": 720,
        "maxFileSizeKb": 150,
        "notes": "不加 Logo",
    },
    {
        "id": "vivo_app_store_triple_9_16",
        "platform": "vivo",
        "name": "商店搜索 - 首位三图",
        "channel": "应用商店",
        "imageForm": "三图",
        "ratio": "9:16",
        "width": 1080,
        "height": 1920,
        "maxFileSizeKb": 150,
    },
    {
        "id": "vivo_app_store_single_root_2_1",
        "platform": "vivo",
        "name": "搜索富媒体 - 单图文",
        "channel": "应用商店",
        "imageForm": "单图",
        "ratio": "16:9",
        "width": 202,
        "height": 142,
        "maxFileSizeKb": 50,
    },
    {
        "id": "vivo_app_store_triple_3_2",
        "platform": "vivo",
        "name": "搜索富媒体 - 三图",
        "channel": "应用商店",
        "imageForm": "三图",
        "ratio": "3:2",
        "width": 320,
        "height": 211,
        "maxFileSizeKb": 80,
    },
    {
        "id": "vivo_app_store_single_16_11",
        "platform": "vivo",
        "name": "顶部 banner",
        "channel": "应用商店",
        "imageForm": "单图",
        "ratio": "16:9",
        "width": 720,
        "height": 498,
        "maxFileSizeKb": 150,
    },
    {
        "id": "xiaomi_app_store_single_16_9",
        "platform": "小米",
        "name": "搜索大图 / 二图 / 横版三图",
        "channel": "应用商店",
        "imageForm": "单图",
        "ratio": "16:9",
        "width": 960,
        "height": 540,
        "maxFileSizeKb": 500,
    },
    {
        "id": "xiaomi_app_store_triple_1_1",
        "platform": "小米",
        "name": "搜索三图",
        "channel": "应用商店",
        "imageForm": "三图",
        "ratio": "1:1",
        "width": 320,
        "height": 320,
        "maxFileSizeKb": 300,
    },
    {
        "id": "xiaomi_app_store_single_16_9_rich",
        "platform": "小米",
        "name": "富媒体大图",
        "channel": "应用商店",
        "imageForm": "单图",
        "ratio": "16:9",
        "width": 960,
        "height": 540,
        "maxFileSizeKb": 500,
    },
    {
        "id": "passthrough_information_feed_single_original",
        "platform": "原图直出",
        "name": "信息流原图直出",
        "channel": "信息流",
        "imageForm": "单图",
        "ratio": "1:1",
        "width": None,
        "height": None,
        "maxFileSizeKb": 999999,
    },
    {
        "id": "passthrough_learning_device_single_original",
        "platform": "原图直出",
        "name": "学习机单图原图直出",
        "channel": "学习机",
        "imageForm": "单图",
        "ratio": "1:1",
        "width": None,
        "height": None,
        "maxFileSizeKb": 999999,
    },
]


RATIO_MAP = {
    "r_1_1": "1:1",
    "r_3_2": "3:2",
    "r_16_9": "16:9",
    "r_9_16": "9:16",
    "original": "1:1",
}

CHANNEL_MAP = {
    "app_store": "应用商店",
    "information_feed": "信息流",
    "learning_device": "学习机",
}

FORM_MAP = {
    "single": "单图",
    "double": "双图",
    "triple": "三图",
}

IMAGE_MARKERS = (
    ("第一张", 1),
    ("第1张", 1),
    ("图一", 1),
    ("图1", 1),
    ("第二张", 2),
    ("第2张", 2),
    ("图二", 2),
    ("图2", 2),
    ("第三张", 3),
    ("第3张", 3),
    ("图三", 3),
    ("图3", 3),
)


def html_escape(value: object) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def current_local_time() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def find_free_port(preferred: int) -> int:
    if preferred:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", preferred)) != 0:
                return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def load_platform_slots(path: Path | None = None) -> list[dict[str, Any]]:
    source = path or DEFAULT_CHANNEL_RULES
    if not source or not source.exists():
        return FALLBACK_SLOTS

    data = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(data.get("placements"), list):
        slots = [normalize_channel_placement(slot) for slot in data["placements"]]
        return slots or FALLBACK_SLOTS

    slots: list[dict[str, Any]] = []
    for platform in data.get("platforms", []):
        platform_name = platform.get("name") or platform.get("id") or "其他"
        for slot in platform.get("slots", []):
            ratio = RATIO_MAP.get(slot.get("sourceRatio") or slot.get("targetRatio"), slot.get("targetRatio") or "1:1")
            if str(ratio).startswith("custom_"):
                ratio = slot.get("sourceRatio") and RATIO_MAP.get(slot["sourceRatio"], "16:9") or "16:9"
            target_width = slot.get("targetWidth")
            target_height = slot.get("targetHeight")
            slots.append(
                normalize_channel_placement(
                    {
                        "id": slot.get("id"),
                        "category": CHANNEL_MAP.get(slot.get("channel"), slot.get("channel") or "其他"),
                        "platform": platform_name,
                        "sub_channel": "",
                        "placement": slot.get("name"),
                        "name": slot.get("name"),
                        "image_form": FORM_MAP.get(slot.get("imageForm"), slot.get("imageForm") or "单图"),
                        "image_count": {"单图": 1, "双图": 2, "三图": 3}.get(FORM_MAP.get(slot.get("imageForm"), ""), 1),
                        "target_width": target_width,
                        "target_height": target_height,
                        "target_size": f"{target_width}x{target_height}" if target_width and target_height else "",
                        "target_ratio": ratio,
                        "render_width": target_width,
                        "render_height": target_height,
                        "render_size": f"{target_width}x{target_height}" if target_width and target_height else "",
                        "directness": "direct",
                        "postprocess": "resize",
                        "max_file_size_kb": slot.get("maxFileSizeKb"),
                        "logo_policy": "forbidden" if "不加" in str(slot.get("notes") or "") else "optional",
                        "cta_policy": "optional" if CHANNEL_MAP.get(slot.get("channel")) == "信息流" else "forbidden",
                        "enabled": True,
                        "disabled_reason": "",
                        "notes": slot.get("notes"),
                    }
                )
            )
    return slots or FALLBACK_SLOTS


def normalize_channel_placement(slot: dict[str, Any]) -> dict[str, Any]:
    category = slot.get("category") or slot.get("channel") or "其他"
    target_width = slot.get("target_width") or slot.get("width")
    target_height = slot.get("target_height") or slot.get("height")
    render_width = slot.get("render_width") or target_width
    render_height = slot.get("render_height") or target_height
    target_size = slot.get("target_size") or (f"{target_width}x{target_height}" if target_width and target_height else "")
    render_size = slot.get("render_size") or (f"{render_width}x{render_height}" if render_width and render_height else "")
    image_form = slot.get("image_form") or slot.get("imageForm") or "单图"
    max_kb = slot.get("max_file_size_kb", slot.get("maxFileSizeKb"))
    return {
        "id": slot.get("id"),
        "category": category,
        "channel": category,
        "platform": slot.get("platform") or "其他",
        "sub_channel": slot.get("sub_channel") or "",
        "name": slot.get("name") or slot.get("placement") or "通用",
        "placement": slot.get("placement") or slot.get("name") or "通用",
        "imageForm": image_form,
        "image_form": image_form,
        "image_count": int(slot.get("image_count") or {"单图": 1, "双图": 2, "三图": 3}.get(str(image_form), 1)),
        "ratio": slot.get("target_ratio") or slot.get("ratio") or "",
        "target_ratio": slot.get("target_ratio") or slot.get("ratio") or "",
        "width": target_width,
        "height": target_height,
        "target_width": target_width,
        "target_height": target_height,
        "target_size": target_size,
        "render_width": render_width,
        "render_height": render_height,
        "render_size": render_size,
        "maxFileSizeKb": max_kb,
        "max_file_size_kb": max_kb,
        "format": slot.get("format") or "",
        "directness": slot.get("directness") or "unknown",
        "directness_label": slot.get("directness_label") or "",
        "postprocess": slot.get("postprocess") or "",
        "logo_policy": slot.get("logo_policy") or "optional",
        "cta_policy": slot.get("cta_policy") or "forbidden",
        "enabled": bool(slot.get("enabled", True)),
        "disabled_reason": slot.get("disabled_reason") or "",
        "notes": slot.get("notes") or "",
        "source": slot.get("source") or "",
    }


def normalize_desired_image_form(context: dict[str, Any]) -> str:
    fields = flatten_context(context)
    for key in ("image_form", "imageForm", "图片形式", "form"):
        value = str(fields.get(key) or "").strip()
        if not value:
            continue
        lowered = value.lower()
        if value in {"单图", "双图", "三图"}:
            return value
        if lowered in {"single", "single_image", "one"} or "单" in value:
            return "单图"
        if lowered in {"double", "two", "two_images"} or "双" in value:
            return "双图"
        if lowered in {"triple", "three", "three_images"} or "三" in value:
            return "三图"
    for value in raw_context_strings(fields):
        if "三图" in value:
            return "三图"
        if "双图" in value or "两图" in value:
            return "双图"
        if "单图" in value:
            return "单图"
    if any(non_empty_text(fields.get(key)) for key in ("短句3", "short3", "copy_text_3")):
        return "三图"
    if any(non_empty_text(fields.get(key)) for key in ("短句2", "short2", "copy_text_2")):
        return "双图"
    if any(non_empty_text(fields.get(key)) for key in ("主标题", "副标题", "main_title", "subtitle", "title")):
        return "单图"
    return ""


def non_empty_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def flatten_context(context: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                fields.setdefault(str(key), child)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(context)
    return fields


def raw_context_strings(fields: dict[str, Any]) -> list[str]:
    values = []
    for key in ("raw", "raw_text", "user_request", "需求", "brief", "intent", "query", "message"):
        value = fields.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    return values


def normalize_channel_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if text in {"信息流", "应用商店", "学习机", "百度"}:
        return text
    if lowered in {"feed", "information_feed", "information-feed", "info_feed", "news_feed"} or "信息流" in text:
        return "信息流"
    if lowered in {"app_store", "app-store", "appstore", "store"} or "应用商店" in text:
        return "应用商店"
    if lowered in {"learning_device", "learning-device", "study_machine"} or "学习机" in text:
        return "学习机"
    if lowered in {"baidu"} or "百度" in text:
        return "百度"
    return ""


def normalize_desired_channels(context: dict[str, Any]) -> list[str]:
    fields = flatten_context(context)
    raw_values: list[Any] = []
    for key in ("channel", "channels", "渠道", "渠道列表", "category", "categories"):
        value = fields.get(key)
        if isinstance(value, list):
            raw_values.extend(value)
        elif value:
            raw_values.append(value)
    raw_values.extend(raw_context_strings(fields))
    channels: list[str] = []
    for value in raw_values:
        name = normalize_channel_name(value)
        if name and name not in channels:
            channels.append(name)
    return channels


def split_image_marker(value: Any) -> tuple[int | None, str]:
    text = str(value or "").strip()
    if not text:
        return None, ""
    stripped = text.lstrip("-• ").strip()
    compact = stripped.replace(" ", "")
    for marker, index in IMAGE_MARKERS:
        marker_len = len(marker)
        if compact.startswith(marker):
            if stripped.startswith(marker):
                body = stripped[marker_len:]
            else:
                body = compact[marker_len:]
            body = body.lstrip(" ：:、,，.-\t")
            return index, body.strip() or text
    return None, text


def normalize_shorthand_copy_items(items: list[Any], desired_form: str) -> dict[str, Any] | None:
    parsed = []
    marker_indices: set[int] = set()
    for item in items:
        index, body = split_image_marker(item)
        if not body:
            continue
        if index:
            marker_indices.add(index)
        parsed.append((index, body))
    if not parsed:
        return None
    image_form = desired_form if desired_form in {"双图", "三图"} else ""
    if not image_form and {1, 2}.issubset(marker_indices):
        image_form = "三图" if 3 in marker_indices else "双图"
    expected_count = {"双图": 2, "三图": 3}.get(image_form, 0)
    if expected_count < 2 or len(parsed) < expected_count:
        return None

    by_index: dict[int, str] = {}
    for position, (marker_index, body) in enumerate(parsed, start=1):
        by_index[marker_index or position] = body
    if not all(by_index.get(index) for index in range(1, expected_count + 1)):
        return None

    result: dict[str, Any] = {"copyDraftId": "draft-1", "imageForm": image_form}
    for index in range(1, expected_count + 1):
        result[f"short{index}"] = by_index[index]
    return result


def normalize_context(context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(context, dict):
        return {}
    normalized = dict(context)
    if any(key in normalized for key in ("copy_drafts", "copyDrafts", "copies", "文案列表")):
        return normalized
    copy_items = normalized.get("copy")
    if not isinstance(copy_items, list):
        return normalized
    draft = normalize_shorthand_copy_items(copy_items, normalize_desired_image_form(normalized))
    if draft:
        normalized["copy_drafts"] = [draft]
    return normalized


def apply_context_image_form(slots: list[dict[str, Any]], desired_form: str) -> list[dict[str, Any]]:
    if not desired_form:
        return slots
    constrained = []
    for slot in slots:
        item = dict(slot)
        slot_form = item.get("imageForm") or item.get("image_form")
        if slot_form and slot_form != desired_form and item.get("enabled", True):
            item["enabled"] = False
            item["disabled_reason"] = f"本次图片形式为{desired_form}，该版位是{slot_form}"
        constrained.append(item)
    return constrained


def apply_context_channels(slots: list[dict[str, Any]], desired_channels: list[str]) -> list[dict[str, Any]]:
    if not desired_channels:
        return slots
    constrained = []
    label = " / ".join(desired_channels)
    for slot in slots:
        item = dict(slot)
        slot_channel = item.get("channel") or item.get("category")
        if slot_channel and slot_channel not in desired_channels and item.get("enabled", True):
            item["enabled"] = False
            item["disabled_reason"] = f"本次渠道为{label}，该版位是{slot_channel}"
        constrained.append(item)
    return constrained


def constrained_slots_for_context(context: dict[str, Any] | None = None, path: Path | None = None) -> list[dict[str, Any]]:
    context = normalize_context(context)
    desired_form = normalize_desired_image_form(context)
    desired_channels = normalize_desired_channels(context)
    slots = load_platform_slots(path)
    slots = apply_context_image_form(slots, desired_form)
    return apply_context_channels(slots, desired_channels)


def slots_by_id(path: Path | None = None, context: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    return {str(slot["id"]): slot for slot in constrained_slots_for_context(context, path) if slot.get("id")}


def file_sha256(path: Path | None) -> str:
    if not path or not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_plugin_version() -> str:
    # Formal skills are shipped inside a role workspace rather than as a
    # plugin package, so there is no plugin metadata dependency here.
    return ""


def enabled_counts_by_form(slots: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"单图": 0, "双图": 0, "三图": 0}
    for slot in slots:
        if slot.get("enabled") is False:
            continue
        form = str(slot.get("imageForm") or slot.get("image_form") or "")
        if form:
            counts[form] = counts.get(form, 0) + 1
    return counts


def disabled_reason_counts(slots: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for slot in slots:
        if slot.get("enabled") is not False:
            continue
        reason = str(slot.get("disabled_reason") or "未注明原因")
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def context_has_reference_image(context: dict[str, Any]) -> bool:
    fields = flatten_context(context)
    for key in (
        "reference_image",
        "referenceImage",
        "reference_images",
        "uploaded_image",
        "uploadedImage",
        "image_path",
        "参考图",
        "参考图片",
    ):
        if fields.get(key):
            return True
    return False


def no_placement_explanation(
    slots: list[dict[str, Any]],
    desired_form: str,
    desired_channels: list[str],
    rules_loaded: bool,
) -> str:
    if desired_form != "双图":
        return ""
    enabled_double = [
        slot
        for slot in slots
        if slot.get("enabled") is not False and (slot.get("imageForm") or slot.get("image_form")) == "双图"
    ]
    if enabled_double:
        return ""

    messages: list[str] = []
    if desired_channels and all(channel == "学习机" for channel in desired_channels):
        messages.append("当前渠道锁定为学习机，学习机一期仅支持单图版位")
    if not rules_loaded:
        messages.append("版位规则未加载，当前使用兜底版位")

    by_id = {str(slot.get("id")): slot for slot in slots}
    huawei_double = by_id.get("huawei-app-slot-slot-480x422")
    if huawei_double:
        huawei_channel = huawei_double.get("channel") or huawei_double.get("category")
        if huawei_double.get("enabled") is False:
            reason = huawei_double.get("disabled_reason") or "未注明原因"
            messages.append(f"华为双图版位当前不可选：{reason}")
        elif desired_channels and huawei_channel not in desired_channels:
            messages.append("华为双图版位存在且可用，但被当前渠道隐藏；请切换到应用商店")

    reasons = []
    for slot in slots:
        if (slot.get("imageForm") or slot.get("image_form")) != "双图" or slot.get("enabled") is not False:
            continue
        reason = str(slot.get("disabled_reason") or "").strip()
        if reason and reason not in reasons:
            reasons.append(reason)
    if reasons:
        messages.append("匹配双图版位的不可选原因：" + "；".join(reasons[:3]))
    if not messages:
        messages.append("当前渠道和图片形式下没有可用双图版位")
    return "；".join(messages) + "。"


def build_payload_diagnostics(
    request_id: str,
    context: dict[str, Any],
    slots: list[dict[str, Any]],
    desired_form: str,
    desired_channels: list[str],
    categories: list[str],
    platform_rules: Path | None,
    started_at: str | None,
) -> dict[str, Any]:
    rules_path = platform_rules or DEFAULT_CHANNEL_RULES
    rules_loaded = bool(rules_path and rules_path.exists())
    counts = enabled_counts_by_form(slots)
    status_channel = desired_channels[0] if desired_channels else (categories[0] if categories else "")
    status_form = desired_form or "未限定"
    enabled_count = counts.get(desired_form, 0) if desired_form else sum(counts.values())
    return {
        "pluginVersion": load_plugin_version(),
        "rulesPath": str(rules_path.resolve()) if rules_path else "",
        "rulesLoaded": rules_loaded,
        "rulesHash": file_sha256(rules_path),
        "desiredImageForm": desired_form,
        "desiredChannels": desired_channels,
        "enabledPlacementCountsByForm": counts,
        "disabledReasonCounts": disabled_reason_counts(slots),
        "serverRequestId": request_id,
        "startedAt": started_at or "",
        "statusSummary": {
            "imageForm": status_form,
            "channel": status_channel or "未限定",
            "enabledDesiredFormCount": enabled_count,
        },
        "hasReferenceImage": context_has_reference_image(context),
        "noPlacementExplanation": no_placement_explanation(slots, desired_form, desired_channels, rules_loaded),
    }


def load_ip_options(manifest_path: Path = ASSET_MANIFEST) -> list[dict[str, Any]]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    options = [
        {"value": "不用", "label": "不用 IP", "asset_id": "", "path": "", "thumb": "", "random": False},
        {"value": "随机", "label": "随机 IP", "asset_id": "__random_ip__", "path": "", "thumb": "", "random": True},
    ]
    for asset in data.get("assets", []):
        if asset.get("kind") != "ip":
            continue
        stage = asset.get("stage_display_name") or asset.get("stage")
        variant = asset.get("variant_display_name") or asset.get("variant")
        suffix = " / ".join([str(x) for x in [stage, variant] if x])
        label = asset.get("asset_name_zh") or f"{asset.get('display_name')}（{suffix}）"
        options.append(
            {
                "value": asset.get("display_name"),
                "label": label,
                "asset_id": asset.get("asset_id"),
                "path": asset.get("path"),
                "thumb": f"/skill-assets/{asset.get('path')}" if asset.get("path") else "",
                "random": False,
            }
        )
    return options


def load_logo_options(manifest_path: Path = ASSET_MANIFEST) -> list[dict[str, Any]]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    options = [{"value": "不用", "label": "不用 Logo", "asset_id": "", "path": "", "thumb": ""}]
    for asset in data.get("assets", []):
        if asset.get("kind") != "logo":
            continue
        options.append(
            {
                "value": asset.get("display_name"),
                "label": asset.get("asset_name_zh") or asset.get("display_name"),
                "asset_id": asset.get("asset_id"),
                "path": asset.get("path"),
                "thumb": f"/skill-assets/{asset.get('path')}" if asset.get("path") else "",
            }
        )
    return options


def default_logo_index(context: dict[str, Any], options: list[dict[str, Any]]) -> int:
    fields = flatten_context(context)
    requested_asset_id = str(fields.get("logo_asset_id") or "").strip()
    requested_path = str(fields.get("logo_reference_path") or "").strip()
    requested_name = str(fields.get("logo") or fields.get("logo_name") or "").strip()
    for index, option in enumerate(options):
        if requested_asset_id and option.get("asset_id") == requested_asset_id:
            return index
        if not requested_asset_id and requested_path and option.get("path") == requested_path:
            return index
        if not requested_asset_id and not requested_path and requested_name and option.get("value") == requested_name:
            return index
    return 0


def load_font_options(font_dir: Path = FONT_DIR) -> list[dict[str, str]]:
    fonts = sorted(font_dir.glob("*.png"))
    return [
        {
            "label": path.stem,
            "asset_id": f"font.{path.stem.replace('字体参考-', 'ref.')}",
            "path": f"assets/font-references/{path.name}",
        }
        for path in fonts
    ]


def count_context_items(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, list):
        return len([item for item in value if item])
    if isinstance(value, dict):
        if value:
            return 1
        return 0
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0
        if "," in text or "，" in text:
            return len([item for item in re_split_commas(text) if item])
        return 1
    return 1


def re_split_commas(text: str) -> list[str]:
    return [item.strip() for item in text.replace("，", ",").split(",") if item.strip()]


def first_text(container: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(container.get(key) or "").strip()
        if value:
            return value
    return ""


def normalize_copy_ref(value: Any, index: int) -> dict[str, Any]:
    if isinstance(value, dict):
        result = {
            "copyId": first_text(value, "copyId", "copy_id", "文案ID", "C-ID"),
            "copyRecordId": first_text(value, "copyRecordId", "copy_record_id", "文案记录ID", "文案record_id"),
            "copyDraftId": first_text(value, "copyDraftId", "copy_draft_id", "draft_id") or f"draft-{index}",
            "mainTitle": first_text(value, "mainTitle", "main_title", "主标题", "标题"),
            "subtitle": first_text(value, "subtitle", "subTitle", "副标题"),
            "short1": first_text(value, "short1", "short_1", "短句1"),
            "short2": first_text(value, "short2", "short_2", "短句2"),
            "short3": first_text(value, "short3", "short_3", "短句3"),
            "copyText": first_text(value, "copyText", "copy_text", "text", "文案", "content"),
            "imageForm": first_text(value, "imageForm", "image_form", "图片形式"),
            "channel": first_text(value, "channel", "渠道"),
        }
        return {key: item for key, item in result.items() if item}
    text = str(value or "").strip()
    return {"copyDraftId": f"draft-{index}", "copyText": text} if text else {}


def normalize_copy_id_ref(value: Any, index: int) -> dict[str, Any]:
    if isinstance(value, dict):
        return normalize_copy_ref(value, index)
    text = str(value or "").strip()
    return {"copyId": text, "copyDraftId": f"draft-{index}"} if text else {}


def extract_copy_refs(context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    context = context or {}
    fields = flatten_context(context)
    for key in ("copy_refs", "copyRefs"):
        value = fields.get(key)
        if isinstance(value, list):
            return [ref for index, item in enumerate(value, start=1) if (ref := normalize_copy_ref(item, index))]

    for key in ("copy_ids", "copyIds"):
        value = fields.get(key)
        if isinstance(value, list):
            return [ref for index, item in enumerate(value, start=1) if (ref := normalize_copy_id_ref(item, index))]
        if isinstance(value, str) and value.strip():
            items = re_split_commas(value) if "," in value or "，" in value else [value]
            return [ref for index, item in enumerate(items, start=1) if (ref := normalize_copy_id_ref(item, index))]

    for key in ("copy_drafts", "copyDrafts", "copies", "文案列表"):
        value = fields.get(key)
        if isinstance(value, list):
            return [ref for index, item in enumerate(value, start=1) if (ref := normalize_copy_ref(item, index))]
        if isinstance(value, str) and value.strip():
            items = re_split_commas(value) if "," in value or "，" in value else [value]
            return [ref for index, item in enumerate(items, start=1) if (ref := normalize_copy_ref(item, index))]

    single = normalize_copy_ref(fields, 1)
    return [single] if single and any(key in single for key in ("copyId", "copyRecordId", "mainTitle", "subtitle", "short1", "copyText")) else []


def infer_copy_count(context: dict[str, Any] | None = None) -> int:
    context = context or {}
    fields = flatten_context(context)
    for key in (
        "copy_count",
        "copyCount",
        "文案数量",
        "copies_count",
    ):
        value = fields.get(key)
        if value is None:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    for key in (
        "copy_drafts",
        "copyDrafts",
        "copies",
        "copy_ids",
        "copyIds",
        "copy_record_ids",
        "copyRecordIds",
        "文案列表",
    ):
        count = count_context_items(fields.get(key))
        if count:
            return count
    if any(non_empty_text(fields.get(key)) for key in ("copy_id", "copyId", "文案ID", "C-ID", "主标题", "副标题", "短句1")):
        return 1
    return 1


def build_config_payload(
    request_id: str,
    context: dict[str, Any] | None = None,
    platform_rules: Path | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    context = normalize_context(context)
    # Formal APP image generation is intentionally direct-generation only for now.
    # Existing-image iteration is not exposed by this local card.
    generation_mode = "explore"
    desired_form = normalize_desired_image_form(context)
    desired_channels = normalize_desired_channels(context)
    copy_refs = extract_copy_refs(context)
    copy_count = max(infer_copy_count(context), len(copy_refs) or 1)
    slots = constrained_slots_for_context(context, platform_rules)
    categories = []
    for slot in slots:
        category = slot.get("category") or slot.get("channel")
        if category and category not in categories:
            categories.append(category)
    diagnostics = build_payload_diagnostics(
        request_id=request_id,
        context=context,
        slots=slots,
        desired_form=desired_form,
        desired_channels=desired_channels,
        categories=categories or ["应用商店", "信息流", "学习机"],
        platform_rules=platform_rules,
        started_at=started_at,
    )
    logo_options = load_logo_options()
    return {
        "request_id": request_id,
        "context": context,
        "deliveryName": extract_delivery_name(context),
        "generationMode": generation_mode,
        "slots": slots,
        "desiredImageForm": desired_form,
        "desiredChannels": desired_channels,
        "copyCount": copy_count,
        "copyRefs": copy_refs,
        "maxGroupCount": MAX_BATCH_GROUP_COUNT,
        "ipOptions": load_ip_options(),
        "fontOptions": load_font_options(),
        "logoOptions": logo_options,
        "defaultLogoIndex": default_logo_index(context, logo_options),
        "categories": categories or ["应用商店", "信息流", "学习机"],
        "diagnostics": diagnostics,
    }


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def read_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def image_sets_payload(output_dir: Path, request_id: str) -> dict[str, Any]:
    path = output_dir / IMAGE_SETS_FILE
    data = read_json_file(path, {"request_id": request_id, "sets": []})
    if isinstance(data, list):
        data = {"request_id": request_id, "sets": data}
    data.setdefault("request_id", request_id)
    data.setdefault("sets", [])
    return data


def merge_image_sets(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(item.get("set_id")): dict(item) for item in existing if item.get("set_id")}
    ordered_ids = [str(item.get("set_id")) for item in existing if item.get("set_id")]
    for item in incoming:
        set_id = str(item.get("set_id"))
        if set_id not in by_id:
            ordered_ids.append(set_id)
        by_id[set_id] = dict(item)
    return [by_id[set_id] for set_id in ordered_ids if set_id in by_id]


def update_image_sets(output_dir: Path, request_id: str, body: dict[str, Any]) -> dict[str, Any]:
    mode = body.get("mode") or "append"
    _, normalized = normalize_sets(body, output_dir)
    current = image_sets_payload(output_dir, request_id)
    if mode == "replace":
        sets = normalized
    else:
        sets = merge_image_sets(current.get("sets") or [], normalized)
    result = {"request_id": str(body.get("request_id") or request_id), "sets": sets}
    atomic_write_json(output_dir / IMAGE_SETS_FILE, result)
    return result


def parse_set_count(value: Any) -> int:
    if value is None or str(value).strip() == "":
        return 1
    text = str(value).strip()
    if not text.isdigit():
        raise ValueError("sets must be an integer between 1 and 50")
    count = int(text)
    if count < 1 or count > 50:
        raise ValueError("sets must be between 1 and 50")
    return count


def parse_positive_int(value: Any, default: int = 1) -> int:
    if value is None or str(value).strip() == "":
        return default
    text = str(value).strip()
    if not text.isdigit():
        raise ValueError("copy_count must be a positive integer")
    parsed = int(text)
    if parsed < 1:
        raise ValueError("copy_count must be a positive integer")
    return parsed


def extract_delivery_name(context: dict[str, Any] | None = None) -> str:
    fields = flatten_context(context or {})
    for key in ("delivery_name", "deliveryName", "direction_name", "directionName", "方向名", "package_name", "包名"):
        value = str(fields.get(key) or "").strip()
        if value:
            return value
    return ""


def normalize_delivery_name(body: dict[str, Any]) -> str:
    value = str(
        body.get("delivery_name")
        or body.get("deliveryName")
        or body.get("direction_name")
        or body.get("directionName")
        or ""
    ).strip()
    if not value:
        raise ValueError("请填写方向名")
    return value


def normalize_config_result(body: dict[str, Any], slot_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    placement_ids = body.get("placement_ids") or body.get("selectedSlotIds") or []
    if not placement_ids and body.get("slot_id"):
        placement_ids = [body["slot_id"]]
    if not isinstance(placement_ids, list):
        raise ValueError("placement_ids must be a list")
    if not placement_ids:
        raise ValueError("select at least one enabled placement")
    if len(placement_ids) != 1:
        raise ValueError("select exactly one enabled placement")
    placements = []
    for placement_id in placement_ids:
        slot = slot_map.get(str(placement_id))
        if not slot:
            raise ValueError(f"unknown placement id: {placement_id}")
        if not slot.get("enabled", True):
            raise ValueError(f"placement is disabled: {placement_id}")
        placements.append(slot)
    if not placements:
        raise ValueError("select at least one enabled placement")

    result = dict(body)
    result["delivery_name"] = normalize_delivery_name(body)
    generation_mode = "explore"
    result["request_id"] = body.get("request_id")
    result["type"] = "image_config"
    result["generation_mode"] = generation_mode
    result["placement_ids"] = [slot["id"] for slot in placements]
    result["placements"] = placements
    result["categories"] = sorted({slot["category"] for slot in placements if slot.get("category")})
    result["channels"] = sorted({slot["channel"] for slot in placements if slot.get("channel")})
    first = placements[0]
    result["slot_id"] = first["id"]
    result["platform"] = first["platform"]
    result["placement"] = first["placement"]
    result["channel"] = first["channel"]
    result["category"] = first["category"]
    result["image_form"] = first["image_form"]
    result["ratio"] = first["target_ratio"]
    result["target_width"] = first["target_width"]
    result["target_height"] = first["target_height"]
    result["target_size"] = first["target_size"]
    result["render_width"] = first["render_width"]
    result["render_height"] = first["render_height"]
    result["render_size"] = first["render_size"]
    result["target_kb"] = first["max_file_size_kb"] or 200
    result["sets"] = parse_set_count(body.get("sets"))
    result["copy_count"] = parse_positive_int(body.get("copy_count") or body.get("copyCount"), 1)
    copy_refs = body.get("copy_refs") if isinstance(body.get("copy_refs"), list) else body.get("copyRefs")
    result["copy_refs"] = copy_refs if isinstance(copy_refs, list) else []
    if result["copy_refs"]:
        result["copy_count"] = max(result["copy_count"], len(result["copy_refs"]))
    result["max_group_count"] = MAX_BATCH_GROUP_COUNT
    result["estimated_group_count"] = result["copy_count"] * len(placements) * result["sets"]
    if result["estimated_group_count"] > MAX_BATCH_GROUP_COUNT:
        raise ValueError(
            f"batch group count exceeds {MAX_BATCH_GROUP_COUNT}: "
            f"{result['copy_count']} copies × {len(placements)} placements × {result['sets']} sets = {result['estimated_group_count']}"
        )
    logo_fields = canonical_logo_fields(body)
    selected_logo = bool(logo_fields["logo_asset_id"])
    forbidden = [slot["id"] for slot in placements if slot.get("logo_policy") == "forbidden"]
    required = [slot["id"] for slot in placements if slot.get("logo_policy") == "required"]
    if selected_logo and forbidden:
        raise ValueError("以下版位禁止使用 Logo：" + ", ".join(forbidden))
    if not selected_logo and required:
        raise ValueError("以下版位必须选择 Logo：" + ", ".join(required))
    result.update(logo_fields)
    result["ip_random"] = bool(body.get("ip_random") or body.get("ip") == "随机")
    result["font_reference_randomized"] = bool(body.get("font_reference_enabled", body.get("fontEnabled", True)))
    screen_ui_required = bool(
        body.get("screen_ui_reference_required")
        or body.get("screenUiReferenceRequired")
        or body.get("ui_reference_required")
        or body.get("uiReferenceRequired")
    )
    result["screen_ui_reference_required"] = screen_ui_required
    result["ui_reference_required"] = screen_ui_required
    if result["ui_reference_required"]:
        result["ui_reference"] = "codex_upload_required"
        result["ui_reference_trigger"] = "recognizable_onion_app_screen"
        result["ui_reference_upload_status"] = body.get("ui_reference_upload_status") or "awaiting_codex_upload"
        result["ui_reference_next_action"] = "保存配置后先提醒用户在 Codex 对话上传截图，建议上传洋葱 APP 界面/功能截图；如果没有截图，只能改成弱化/模糊屏幕内容后继续。收到截图前不能进入 prompt、validate-only 或 render。"
    else:
        result["ui_reference"] = "none"
        result["ui_reference_trigger"] = "none"
        result["ui_reference_upload_status"] = "not_required"
        result["ui_reference_next_action"] = ""
    return result


def build_config_html(payload: dict[str, Any]) -> str:
    data_json = json.dumps(payload, ensure_ascii=False)
    request_id = html_escape(payload["request_id"])
    template = CONFIG_TEMPLATE.read_text(encoding="utf-8")
    return template.replace("__REQUEST_ID__", request_id).replace("__DATA_JSON__", data_json)


def build_request_mismatch_html(server_request_id: str, url_request_id: str) -> str:
    server_id = html_escape(server_request_id)
    url_id = html_escape(url_request_id)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>旧配置页或旧 request</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif; background: #f6f7f9; color: #1e2329; }}
    main {{ max-width: 720px; margin: 64px auto; background: #fff; border: 1px solid #dfe3e8; border-radius: 8px; padding: 24px; }}
    h1 {{ margin: 0 0 16px; font-size: 20px; }}
    p {{ line-height: 1.7; }}
    code {{ background: #f1f3f5; border-radius: 4px; padding: 2px 6px; }}
  </style>
</head>
<body>
  <main>
    <h1>你打开的是旧配置页或旧 request</h1>
    <p>当前服务 request_id: <code>{server_id}</code></p>
    <p>URL request_id: <code>{url_id}</code></p>
    <p>请打开本次启动输出里的链接。</p>
  </main>
</body>
</html>"""


class OnionInteractionHandler(SimpleHTTPRequestHandler):
    server_version = "OnionInteraction/1.0"

    def translate_path(self, path: str) -> str:
        parsed = urlparse(path)
        clean = posixpath.normpath(unquote(parsed.path).lstrip("/"))
        output_root = self.server.output_dir.resolve()  # type: ignore[attr-defined]
        if clean in {"", "."}:
            clean = "image-config"
        if clean == "image-config":
            return str(self.server.output_dir / "__image_config_virtual__.html")  # type: ignore[attr-defined]
        if clean.startswith("skill-assets/"):
            rel = clean.removeprefix("skill-assets/")
            target = (SKILL_DIR / rel).resolve()
            skill_root = SKILL_DIR.resolve()
            if target == skill_root or skill_root in target.parents:
                return str(target)
            return str(self.server.output_dir / "__forbidden__")  # type: ignore[attr-defined]
        target = (self.server.output_dir / clean).resolve()  # type: ignore[attr-defined]
        if target == output_root or output_root in target.parents:
            return str(target)
        return str(output_root / "__forbidden__")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/image-sets":
            response = image_sets_payload(self.server.output_dir, self.server.request_id)  # type: ignore[attr-defined]
            self.send_json(response)
            return
        if parsed.path in {"/", "/image-config"}:
            qs = parse_qs(parsed.query)
            requested_ids = qs.get("request_id", [])  # type: ignore[attr-defined]
            server_request_id = self.server.request_id  # type: ignore[attr-defined]
            if requested_ids and requested_ids[0] != server_request_id:
                html = build_request_mismatch_html(server_request_id, requested_ids[0])
                body = html.encode("utf-8")
                self.send_response(409)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            request_id = requested_ids[0] if requested_ids else server_request_id
            html = build_config_html(self.server.payload_for(request_id))  # type: ignore[attr-defined]
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def send_json(self, response: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(response, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        output_names = {
            "/api/image-config": "image-config-result.json",
            "/api/image-selection": "image-selection-result.json",
        }
        if parsed.path not in output_names and parsed.path != "/api/image-sets":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("POST body must be a JSON object")
            body_request_id = str(data.get("request_id") or "")
            server_request_id = str(self.server.request_id)  # type: ignore[attr-defined]
            if body_request_id != server_request_id:
                self.send_json(
                    {
                        "ok": False,
                        "error": f"request_id mismatch: body={body_request_id or '<missing>'}, server={server_request_id}",
                    },
                    409,
                )
                return
            if parsed.path == "/api/image-sets":
                result = update_image_sets(self.server.output_dir, self.server.request_id, data)  # type: ignore[attr-defined]
                output_path = self.server.output_dir / IMAGE_SETS_FILE  # type: ignore[attr-defined]
                response = {"ok": True, "path": str(output_path), "result": result}
            else:
                output_path = self.server.output_dir / output_names[parsed.path]  # type: ignore[attr-defined]
                if parsed.path == "/api/image-config":
                    data = normalize_config_result(data, slots_by_id(self.server.platform_rules, self.server.context))  # type: ignore[attr-defined]
                atomic_write_json(output_path, data)
                response = {"ok": True, "path": str(output_path), "result": data}
            self.send_json(response)
            return
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
            self.send_json(response, 400)

    def log_message(self, format: str, *args: Any) -> None:
        print(format % args, file=sys.stderr)


class OnionInteractionServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        output_dir: Path,
        request_id: str,
        context: dict[str, Any] | None,
        platform_rules: Path | None,
    ) -> None:
        super().__init__(server_address, OnionInteractionHandler)
        self.output_dir = output_dir.resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.request_id = request_id
        self.context = normalize_context(context)
        self.platform_rules = platform_rules
        self.started_at = current_local_time()

    def payload_for(self, request_id: str) -> dict[str, Any]:
        return build_config_payload(
            request_id=request_id,
            context=self.context,
            platform_rules=self.platform_rules,
            started_at=self.started_at,
        )


def parse_context(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    path = Path(value)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8-sig"))
    return json.loads(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local Onion image interaction server.")
    parser.add_argument("--request-id", required=True)
    parser.add_argument(
        "--output-dir",
        help="Formal roles pass the task version 02_过程 directory; omitted uses the maintenance .runtime path.",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--context", help="JSON string or JSON file path with upstream copy/direction context")
    parser.add_argument("--platform-rules", help="placement rules JSON path; defaults to plugin config/channel-placement-rules.json")
    args = parser.parse_args(argv)

    output_dir = resolve_output_dir(args.output_dir, args.request_id)
    port = find_free_port(args.port)
    platform_rules = Path(args.platform_rules).expanduser() if args.platform_rules else DEFAULT_CHANNEL_RULES
    if not platform_rules.exists():
        platform_rules = None
    server = OnionInteractionServer(
        ("127.0.0.1", port),
        output_dir=output_dir,
        request_id=args.request_id,
        context=parse_context(args.context),
        platform_rules=platform_rules,
    )
    url = f"http://127.0.0.1:{port}/image-config?request_id={args.request_id}"
    result_path = output_dir / "image-config-result.json"
    print(json.dumps({"ok": True, "url": url, "result_path": str(result_path)}, ensure_ascii=False), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
