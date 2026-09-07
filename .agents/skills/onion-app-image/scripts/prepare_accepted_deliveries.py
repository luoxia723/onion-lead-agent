#!/usr/bin/env python3
"""Locally prepare every accepted APP image for formal delivery."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from PIL import Image


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from image_compress import compress  # noqa: E402


UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value: str, fallback: str) -> str:
    text = UNSAFE_NAME.sub("-", str(value or "").strip())
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[-_]{2,}", "_", text).strip(" .-_")
    return text or fallback


def task_paths(selection_result: Path) -> dict[str, Path]:
    selection_result = selection_result.expanduser().resolve()
    version_root = selection_result.parent.parent
    paths = {
        "selection": selection_result,
        "version_root": version_root,
        "process": version_root / "02_过程",
        "candidate": version_root / "03_候选",
        "delivery": version_root / "04_交付",
        "quality": version_root / "05_质检",
        "task_index": version_root.parent / "任务索引.json",
    }
    missing = [
        str(path)
        for name, path in paths.items()
        if name != "selection" and name != "task_index" and not path.is_dir()
    ]
    if not selection_result.is_file():
        missing.append(str(selection_result))
    if not paths["task_index"].is_file():
        missing.append(str(paths["task_index"]))
    if missing:
        raise ValueError("selection result is not inside a complete task version: " + ", ".join(missing))
    return paths


def accepted_schemes(selection: dict[str, Any]) -> list[dict[str, Any]]:
    value = selection.get("accepted_schemes")
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("accepted_schemes must be a list of objects")
    return list(value)


def scheme_id(scheme: dict[str, Any], position: int) -> str:
    value = str(scheme.get("set_id") or scheme.get("id") or "").strip()
    if not value:
        raise ValueError(f"accepted scheme {position} has no stable id")
    return value


def scheme_sources(scheme: dict[str, Any], candidate_root: Path) -> list[Path]:
    raw = scheme.get("thumb")
    if raw is None:
        raw = [item.get("path") if isinstance(item, dict) else item for item in scheme.get("images", [])]
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"accepted scheme has no images: {scheme.get('set_id')}")

    resolved_root = candidate_root.resolve()
    sources = []
    for item in raw:
        path = Path(str(item)).expanduser()
        path = (candidate_root / path).resolve() if not path.is_absolute() else path.resolve()
        if not path.is_file():
            raise ValueError(f"accepted source does not exist: {path}")
        if resolved_root not in path.parents:
            raise ValueError(f"accepted source must stay under 03_候选: {path}")
        sources.append(path)
    return sources


def jobs_for_candidate(
    candidate_id: str,
    image_count: int,
    jobs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    matches = [
        job
        for job in jobs
        if str(job.get("set_id") or "") == candidate_id
        or str(job.get("job_id") or "").startswith(candidate_id + "-slot-")
    ]
    matches.sort(key=lambda item: int(item.get("slot") or 1))
    if len(matches) != image_count:
        raise ValueError(
            f"candidate {candidate_id} has {image_count} images but {len(matches)} render jobs"
        )
    return matches


def positive_int(*values: Any) -> int | None:
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def export_spec(job: dict[str, Any], placement: dict[str, Any]) -> dict[str, Any]:
    width = positive_int(job.get("target_width"), placement.get("target_width"))
    height = positive_int(job.get("target_height"), placement.get("target_height"))
    target_kb = positive_int(
        job.get("target_kb"),
        placement.get("max_file_size_kb"),
        placement.get("target_kb"),
        200,
    )
    if not width or not height or not target_kb:
        raise ValueError(f"missing exact delivery spec for job: {job.get('job_id')}")
    return {
        "placement_id": str(job.get("placement_id") or placement.get("id") or ""),
        "platform": str(job.get("platform") or placement.get("platform") or ""),
        "placement": str(
            job.get("placement") or placement.get("placement") or placement.get("name") or ""
        ),
        "target_width": width,
        "target_height": height,
        "target_kb": target_kb,
    }


def verify_delivery(path: Path, spec: dict[str, Any]) -> dict[str, Any]:
    with Image.open(path) as image:
        image.load()
        image_format = str(image.format or "").upper()
        dimensions = [image.width, image.height]
    byte_count = path.stat().st_size
    expected = [int(spec["target_width"]), int(spec["target_height"])]
    if image_format != "JPEG" or dimensions != expected or byte_count > int(spec["target_kb"]) * 1024:
        raise ValueError(
            f"delivery verification failed: {path} "
            f"format={image_format} dimensions={dimensions} bytes={byte_count}"
        )
    return {
        "mime_type": "image/jpeg",
        "width": dimensions[0],
        "height": dimensions[1],
        "byte_count": byte_count,
        "sha256": file_sha256(path),
    }


def prepare_accepted_deliveries(selection_result: Path) -> dict[str, Any]:
    paths = task_paths(selection_result)
    selection = load_json(paths["selection"])
    config = load_json(paths["process"] / "image-config-result.json")
    manifest = load_json(paths["process"] / "image-render-manifest.json")
    task_index = load_json(paths["task_index"])

    placements = [item for item in config.get("placements", []) if isinstance(item, dict)]
    if len(placements) != 1:
        raise ValueError("saved config must contain exactly one placement")
    placement = placements[0]
    jobs = [item for item in manifest.get("jobs", []) if isinstance(item, dict)]
    schemes = accepted_schemes(selection)

    file_stem = safe_name(str(task_index.get("file_stem") or "APP图片"), "APP图片")
    version = safe_name(paths["version_root"].name, "v001")
    quality_result = paths["quality"] / f"{file_stem}_交付规格质检_{version}.json"
    selection_sha256 = file_sha256(paths["selection"])
    previous = load_json(quality_result) if quality_result.is_file() else None
    if previous and previous.get("selection_sha256") != selection_sha256:
        raise ValueError("selection changed after delivery; create a new task version")

    previous_files = {
        (str(item.get("candidate_id")), int(item.get("image_position") or 0)): item
        for item in (previous or {}).get("files", [])
        if isinstance(item, dict)
    }

    records = []
    for scheme_position, scheme in enumerate(schemes, start=1):
        candidate_id = scheme_id(scheme, scheme_position)
        sources = scheme_sources(scheme, paths["candidate"])
        matched_jobs = jobs_for_candidate(candidate_id, len(sources), jobs)
        for image_position, (source, job) in enumerate(zip(sources, matched_jobs), start=1):
            spec = export_spec(job, placement)
            source_sha256 = file_sha256(source)
            delivery = paths["delivery"] / (
                f"{file_stem}_方案{scheme_position:03d}_图{image_position:02d}_{version}.jpg"
            )
            previous_file = previous_files.get((candidate_id, image_position))
            if delivery.exists():
                if not previous_file or previous_file.get("source_sha256") != source_sha256:
                    raise ValueError(f"existing delivery does not match accepted source: {delivery}")
                verification = verify_delivery(delivery, spec)
                reused = True
            else:
                compress(
                    str(source),
                    str(delivery),
                    target_kb=int(spec["target_kb"]),
                    target_width=int(spec["target_width"]),
                    target_height=int(spec["target_height"]),
                )
                verification = verify_delivery(delivery, spec)
                reused = False
            records.append(
                {
                    "candidate_id": candidate_id,
                    "image_position": image_position,
                    "job_id": str(job.get("job_id") or ""),
                    "source": str(source),
                    "source_sha256": source_sha256,
                    "delivery": str(delivery),
                    "reused_existing": reused,
                    **spec,
                    **verification,
                }
            )

    payload = {
        "schema_version": "onion_app_image_local_delivery_v1",
        "task_id": str(task_index.get("task_id") or selection.get("request_id") or ""),
        "version": version,
        "processor": "local-pillow",
        "selection_result": str(paths["selection"]),
        "selection_sha256": selection_sha256,
        "accepted_scheme_count": len(schemes),
        "delivery_file_count": len(records),
        "output_dir": str(paths["delivery"]),
        "files": records,
    }
    atomic_write_json(quality_result, payload)
    payload["quality_result"] = str(quality_result)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-result", required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_accepted_deliveries(Path(args.selection_result))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
