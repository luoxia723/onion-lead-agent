#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


METADATA_FIELDS = (
    "购买动因名称", "购买动因来源", "信息屋", "文案数量", "创意参考",
    "服务事实来源", "渠道与入口", "当前权益与体验时长", "唯一CTA",
    "用户上传前贴", "人工状态",
)
DETAIL_FIELDS = (
    "采用创意结构", "创意来源", "实际参考素材", "主体验链", "当前权益",
    "线索行动", "前贴状态", "预计时长", "人工状态",
)
OVERVIEW_HEADER = "| 文案 | 标题 | 创意结构 | 预计时长 | 人工状态 | 文案详情 |"
COPY_RE = re.compile(
    r'(?ms)^<a id="copy-(\d{3})"></a>\n'
    r'^## (文案-(\d{3}))｜(.+?)\n'
    r'(.*?)(?=^<a id="copy-|\Z)'
)
TABLE_ROW_RE = re.compile(r"(?m)^\| ([^|]+) \| (.+) \|$")
CREATIVE_SOURCE_RE = re.compile(
    r"(?:外部视频创意报告[^\n|]*EC-\d{3}|内部视频创意报告[^\n|]*IC-\d{3})"
)
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\([^)]+\)")


def _table_values(text: str) -> dict[str, str]:
    return {label.strip(): value.strip() for label, value in TABLE_ROW_RE.findall(text)}


def _between(body: str, start: str, end: str | None = None) -> str:
    if end is None:
        match = re.search(rf"(?ms)^{re.escape(start)}\s*\n(.*)$", body)
    else:
        match = re.search(
            rf"(?ms)^{re.escape(start)}\s*\n(.*?)(?=^{re.escape(end)}\s*$)",
            body,
        )
    return match.group(1).strip() if match else ""


def validate(text: str) -> list[str]:
    errors: list[str] = []
    if not re.search(r"^# 线索视频口播文案(?:｜|$)", text, re.M):
        errors.append("title_invalid")
    if "## 本批信息" not in text:
        errors.append("batch_info_required")
    if "## 文案一览" not in text or OVERVIEW_HEADER not in text:
        errors.append("overview_required")

    metadata = _table_values(text.split("## 文案一览", 1)[0])
    for field in METADATA_FIELDS:
        if not metadata.get(field):
            errors.append(f"missing_metadata:{field}")

    entries = list(COPY_RE.finditer(text))
    declared_value = metadata.get("文案数量", "")
    declared = int(declared_value) if declared_value.isdigit() else None
    if declared is None or declared != len(entries):
        errors.append("copy_count_mismatch")
    numbers = [int(match.group(3)) for match in entries]
    if numbers != list(range(1, len(entries) + 1)):
        errors.append("copy_ids_not_consecutive")

    for match in entries:
        anchor_number, copy_id, number, _, body = match.groups()
        if anchor_number != number:
            errors.append(f"{copy_id}:anchor_mismatch")
        if f"](#copy-{number})" not in text:
            errors.append(f"{copy_id}:overview_detail_link_missing")
        if body.count("### 正式口播") != 1 or body.count("### 使用依据") != 1:
            errors.append(f"{copy_id}:required_headings_invalid")

        values = _table_values(_between(body, "### 使用依据"))
        for field in DETAIL_FIELDS:
            if not values.get(field):
                errors.append(f"{copy_id}:missing_detail:{field}")

        structure = values.get("采用创意结构", "")
        source = values.get("创意来源", "")
        reference = values.get("实际参考素材", "")
        if structure.startswith("原创"):
            if source != "原创" or reference != "无":
                errors.append(f"{copy_id}:original_source_or_reference_invalid")
        else:
            if not CREATIVE_SOURCE_RE.search(source):
                errors.append(f"{copy_id}:creative_source_invalid")
            if not MARKDOWN_LINK_RE.search(reference):
                errors.append(f"{copy_id}:actual_reference_material_required")
        if "未使用" in metadata.get("创意参考", "") and not structure.startswith("原创"):
            errors.append(f"{copy_id}:report_structure_forbidden_without_reports")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    errors = validate(args.report.read_text(encoding="utf-8"))
    if errors:
        print("\n".join(errors))
        return 1
    print("lead_video_copy_valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
