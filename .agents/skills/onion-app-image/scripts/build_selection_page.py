#!/usr/bin/env python3
"""
Build the local image selection HTML page from rendered image set metadata.

The template expects a compact legacy shape (`set_id`, `thumb`, `meta`,
`source`). This script accepts that shape or the newer image_groups-oriented
shape (`schemes[].images[].path`) and normalizes it so the page always contains
the generated images instead of an empty template.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_TEMPLATE = SKILL_DIR / "templates" / "image-selection.html"


def load_json_arg(value: str) -> Any:
    if value.startswith("@"):
        return json.loads(Path(value[1:]).read_text(encoding="utf-8"))
    path = Path(value)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(value)


def materialize_image_path(path_value: str, output_dir: Path) -> str:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        return str(path)

    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"image file not found: {resolved}")

    output_root = output_dir.resolve()
    try:
        return str(resolved.relative_to(output_root))
    except ValueError:
        assets_dir = output_root / "selection-assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()[:8]
        target = assets_dir / f"{resolved.stem}-{digest}{resolved.suffix}"
        if not target.exists():
            shutil.copy2(resolved, target)
        return str(target.relative_to(output_root))


def normalize_meta(source: dict[str, Any]) -> dict[str, Any]:
    meta = dict(source.get("meta") or {})
    aliases = {
        "category": "大类",
        "platform": "渠道平台",
        "placement_id": "版位ID",
        "slot_id": "版位ID",
        "channel": "渠道",
        "form": "图片形式",
        "image_form": "图片形式",
        "imageForm": "图片形式",
        "ratio": "比例",
        "ip": "IP形象",
        "placement": "版位",
        "logo": "Logo",
        "cta": "CTA文字",
        "target_size": "目标尺寸",
        "target_width": "目标宽度",
        "target_height": "目标高度",
        "target_kb": "目标KB",
    }
    for normalized, raw in aliases.items():
        if normalized in meta:
            continue
        if normalized in source:
            meta[normalized] = source[normalized]
        elif raw in source:
            meta[normalized] = source[raw]
    findings = (
        source.get("review_findings")
        or source.get("content_findings")
        or source.get("advisories")
        or meta.get("review_findings")
        or []
    )
    if isinstance(findings, str):
        findings = [findings]
    if isinstance(findings, list):
        normalized_findings = [str(item).strip() for item in findings if str(item).strip()]
        if normalized_findings:
            meta["review_findings"] = normalized_findings
    return meta


def normalize_source(source: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(source.get("source"), dict):
        return source["source"]

    result = {
        "copyId": source.get("copy_id") or source.get("copyId") or source.get("文案ID"),
        "copyRecordId": source.get("copy_record_id") or source.get("copyRecordId") or source.get("文案record_id") or source.get("文案记录ID"),
        "copySummary": source.get("copy_summary") or source.get("copySummary") or source.get("文案摘要"),
        "directionId": source.get("direction_id") or source.get("directionId") or source.get("方向ID"),
        "directionRecordId": source.get("direction_record_id") or source.get("directionRecordId") or source.get("方向record_id") or source.get("方向记录ID"),
        "direction": source.get("direction") or source.get("方向摘要"),
    }
    return result if any(result.values()) else None


def normalize_sets(data: Any, output_dir: Path) -> tuple[str, list[dict[str, Any]]]:
    if isinstance(data, dict):
        request_id = str(data.get("request_id") or data.get("requestId") or output_dir.name)
        raw_sets = data.get("schemes") or data.get("sets") or data.get("SETS_DATA")
    else:
        request_id = output_dir.name
        raw_sets = data

    if not isinstance(raw_sets, list) or not raw_sets:
        raise ValueError("sets data must contain a non-empty schemes/sets array")

    normalized = []
    for index, raw in enumerate(raw_sets, start=1):
        if not isinstance(raw, dict):
            raise ValueError("each set must be an object")
        raw_status = str(raw.get("status") or "").strip().lower()
        if raw_status and raw_status != "completed":
            continue

        images = raw.get("thumb")
        if images is None:
            images = [
                item["path"] if isinstance(item, dict) else item
                for item in raw.get("images", [])
            ]
        if not isinstance(images, list) or not images:
            raise ValueError(f"set {index} must include thumb or images")

        normalized.append(
            {
                "set_id": str(raw.get("set_id") or raw.get("id") or f"set{index}"),
                "thumb": [materialize_image_path(str(path), output_dir) for path in images],
                "meta": normalize_meta(raw),
                "source": normalize_source(raw),
            }
        )

    if not normalized:
        raise ValueError("sets data does not contain any completed image set")

    return request_id, normalized


def build_html(template: str, request_id: str, sets: list[dict[str, Any]]) -> str:
    return (
        template.replace("{{REQUEST_ID}}", request_id)
        .replace("{{SETS_DATA}}", json.dumps(sets, ensure_ascii=False))
    )


def write_image_sets_index(output_dir: Path, request_id: str, sets: list[dict[str, Any]]) -> Path:
    path = output_dir / "image-sets.json"
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps({"request_id": request_id, "sets": sets}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build onion image selection HTML.")
    parser.add_argument("--sets-data", required=True, help="JSON string, JSON file path, or @file")
    parser.add_argument("--output", required=True, help="Output HTML path")
    parser.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    args = parser.parse_args(argv)

    try:
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        request_id, sets = normalize_sets(load_json_arg(args.sets_data), output.parent)
        template = Path(args.template).read_text(encoding="utf-8")
        html = build_html(template, request_id, sets)
        output.write_text(html, encoding="utf-8")
        image_sets = write_image_sets_index(output.parent, request_id, sets)
        print(json.dumps({"ok": True, "html": str(output), "image_sets": str(image_sets), "url": output.resolve().as_uri()}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
