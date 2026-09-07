#!/usr/bin/env python3
"""Package already validated APP image delivery JPEGs without recompression."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def package_accepted_images(delivery_result: Path) -> dict[str, Any]:
    delivery_result = delivery_result.expanduser().resolve()
    result = load_json(delivery_result)
    if result.get("schema_version") != "onion_app_image_local_delivery_v1":
        raise ValueError("delivery result schema is invalid")

    version_root = delivery_result.parent.parent
    delivery_root = (version_root / "04_交付").resolve()
    package_root = version_root / "06_打包"
    task_index = load_json(version_root.parent / "任务索引.json")
    files = [item for item in result.get("files", []) if isinstance(item, dict)]
    if not files:
        raise ValueError("delivery result has no files to package")

    verified = []
    for item in files:
        path = Path(str(item.get("delivery") or "")).expanduser().resolve()
        if not path.is_file() or delivery_root not in path.parents:
            raise ValueError(f"delivery file is missing or outside 04_交付: {path}")
        byte_count = path.stat().st_size
        sha256 = file_sha256(path)
        if byte_count != int(item.get("byte_count") or -1) or sha256 != item.get("sha256"):
            raise ValueError(f"delivery receipt mismatch: {path}")
        verified.append({"path": path, "byte_count": byte_count, "sha256": sha256})

    file_stem = str(task_index.get("file_stem") or "APP图片")
    version = str(result.get("version") or version_root.name)
    package_root.mkdir(parents=True, exist_ok=True)
    zip_path = package_root / f"{file_stem}_交付包_{version}.zip"
    manifest_path = package_root / f"{file_stem}_交付包_{version}_交付清单.json"
    temp_zip = zip_path.with_suffix(".zip.tmp")

    portable_files = [
        {
            "path": item["path"].name,
            "byte_count": item["byte_count"],
            "sha256": item["sha256"],
        }
        for item in verified
    ]
    portable_manifest = {
        "schema_version": "onion_delivery_package_v1",
        "task_id": str(result.get("task_id") or task_index.get("task_id") or ""),
        "version": version,
        "files": portable_files,
    }
    root_name = f"{file_stem}_{version}"

    with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in verified:
            archive.write(item["path"], f"{root_name}/{item['path'].name}")
        archive.writestr(
            f"{root_name}/交付清单.json",
            json.dumps(portable_manifest, ensure_ascii=False, indent=2) + "\n",
        )
    temp_zip.replace(zip_path)
    atomic_write_json(manifest_path, portable_manifest)

    return {
        "task_id": portable_manifest["task_id"],
        "version": version,
        "delivery_file_count": len(verified),
        "zip": str(zip_path),
        "manifest": str(manifest_path),
        "files": portable_files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery-result", required=True)
    args = parser.parse_args(argv)
    try:
        result = package_accepted_images(Path(args.delivery_result))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
