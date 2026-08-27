#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def contract_timezone(name: str) -> ZoneInfo | timezone:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == "Asia/Shanghai":
            return timezone(timedelta(hours=8), name)
        raise


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_project_root(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    for candidate in (Path.cwd(), *Path(__file__).resolve().parents):
        if (candidate / "工作区").is_dir():
            return candidate
        if (candidate / "AGENTS.md").is_file() and (candidate / "Skills").is_dir():
            return candidate
    raise RuntimeError("无法定位角色工作区或主仓库根目录")


def load_contract() -> dict[str, Any]:
    script = Path(__file__).resolve()
    candidates = (
        script.parents[1] / "references" / "artifact-layout.json",
        script.parents[1] / ".agents" / "references" / "artifact-layout.json",
    )
    for candidate in candidates:
        if candidate.is_file():
            value = json.loads(candidate.read_text(encoding="utf-8"))
            if value.get("schema_version") != "onion_artifact_layout_v1":
                raise RuntimeError("产物目录合同版本无效")
            return value
    raise RuntimeError("缺少artifact-layout.json")


def version_paths(task_root: Path, version: str, contract: dict[str, Any]) -> dict[str, str]:
    root = task_root / version
    return {phase: str(root / phase) for phase in contract["phases"]}


def create_version(task_root: Path, version: str, contract: dict[str, Any], *, title: str, business_line: str | None) -> dict[str, Any]:
    paths = version_paths(task_root, version, contract)
    for path in paths.values():
        Path(path).mkdir(parents=True, exist_ok=False)
    now = datetime.now(contract_timezone(contract["timezone"])).isoformat(timespec="seconds")
    manifest = {
        "schema_version": "onion_artifact_task_version_v1",
        "task_id": task_root.name,
        "version": version,
        "title": title,
        "business_line": business_line,
        "status": "created",
        "created_at": now,
        "updated_at": now,
        "files": [],
    }
    write_json(Path(paths["00_任务"]) / "任务清单.json", manifest)
    return {"version": version, "version_root": str(task_root / version), "phases": paths}


def create_task(args: argparse.Namespace) -> dict[str, Any]:
    contract = load_contract()
    info = contract["artifact_types"].get(args.code)
    if info is None:
        raise RuntimeError(f"未知产物代码：{args.code}")
    root = find_project_root(args.project_root)
    now = datetime.now(contract_timezone(contract["timezone"]))
    date_dir = now.strftime("%Y-%m-%d")
    task_id = f"{args.code}-{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"
    task_root = root / contract["workspace_root"] / date_dir / info["category"] / task_id
    task_root.mkdir(parents=True, exist_ok=False)
    version = create_version(task_root, "v001", contract, title=args.title, business_line=args.business_line)
    index = {
        "schema_version": "onion_artifact_task_index_v1",
        "task_id": task_id,
        "artifact_code": args.code,
        "artifact_label": info["label"],
        "skill": info["skill"],
        "title": args.title,
        "business_line": args.business_line,
        "date": date_dir,
        "timezone": contract["timezone"],
        "current_version": "v001",
        "versions": ["v001"],
    }
    write_json(task_root / "任务索引.json", index)
    extension = info.get("primary_extension")
    suggested = None
    if extension:
        suggested = f"{task_id}_{info['label']}_v001.{extension}"
    return {"task_root": str(task_root), "task_id": task_id, "suggested_primary_file": suggested, **version}


def load_index(task_root: Path, contract: dict[str, Any]) -> dict[str, Any]:
    path = task_root / "任务索引.json"
    if not path.is_file():
        raise RuntimeError("任务目录缺少任务索引.json")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "onion_artifact_task_index_v1":
        raise RuntimeError("任务索引版本无效")
    if not re.fullmatch(contract["task_id_pattern"], str(value.get("task_id") or "")):
        raise RuntimeError("任务ID不符合合同")
    if value["task_id"] != task_root.name:
        raise RuntimeError("任务目录名与任务ID不一致")
    return value


def new_version(args: argparse.Namespace) -> dict[str, Any]:
    contract = load_contract()
    task_root = args.task_root.expanduser().resolve()
    index = load_index(task_root, contract)
    number = max(int(value[1:]) for value in index["versions"]) + 1
    version = f"v{number:03d}"
    result = create_version(
        task_root,
        version,
        contract,
        title=index["title"],
        business_line=index.get("business_line"),
    )
    index["versions"].append(version)
    index["current_version"] = version
    write_json(task_root / "任务索引.json", index)
    return {"task_root": str(task_root), "task_id": index["task_id"], **result}


def version_manifest(task_root: Path, version: str) -> tuple[Path, dict[str, Any]]:
    path = task_root / version / "00_任务" / "任务清单.json"
    if not path.is_file():
        raise RuntimeError("版本缺少任务清单.json")
    return path, json.loads(path.read_text(encoding="utf-8"))


def scan_version_files(version_root: Path, manifest_path: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for path in sorted(version_root.rglob("*")):
        if not path.is_file() or path == manifest_path:
            continue
        files.append(
            {
                "path": path.relative_to(version_root).as_posix(),
                "byte_count": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    return files


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    contract = load_contract()
    task_root = args.task_root.expanduser().resolve()
    index = load_index(task_root, contract)
    version = args.version or index["current_version"]
    manifest_path, manifest = version_manifest(task_root, version)
    version_root = task_root / version
    files = scan_version_files(version_root, manifest_path)
    manifest["status"] = args.status
    manifest["updated_at"] = datetime.now(contract_timezone(contract["timezone"])).isoformat(timespec="seconds")
    manifest["files"] = files
    write_json(manifest_path, manifest)
    return {"task_id": index["task_id"], "version": version, "status": args.status, "file_count": len(files)}


def package(args: argparse.Namespace) -> dict[str, Any]:
    contract = load_contract()
    task_root = args.task_root.expanduser().resolve()
    index = load_index(task_root, contract)
    version = args.version or index["current_version"]
    delivery = task_root / version / "04_交付"
    files = [path for path in sorted(delivery.rglob("*")) if path.is_file()]
    if not files:
        raise RuntimeError("04_交付为空，不能打包")
    package_dir = task_root / version / "06_打包"
    stem = f"{index['task_id']}_{index['artifact_label']}交付包_{version}"
    output = package_dir / f"{stem}.zip"
    manifest_path = package_dir / f"{stem}_交付清单.json"
    if output.exists() or manifest_path.exists():
        raise RuntimeError("交付包已存在，不覆盖")
    entries = [
        {
            "path": path.relative_to(delivery).as_posix(),
            "byte_count": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in files
    ]
    package_manifest = {
        "schema_version": "onion_delivery_package_v1",
        "task_id": index["task_id"],
        "artifact_code": index["artifact_code"],
        "artifact_label": index["artifact_label"],
        "version": version,
        "files": entries,
    }
    root_name = f"{index['task_id']}_{index['artifact_label']}_{version}"
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, f"{root_name}/{path.relative_to(delivery).as_posix()}")
        archive.writestr(
            f"{root_name}/交付清单.json",
            json.dumps(package_manifest, ensure_ascii=False, indent=2) + "\n",
        )
    write_json(manifest_path, {**package_manifest, "zip_sha256": sha256(output)})
    task_manifest_path, task_manifest = version_manifest(task_root, version)
    task_manifest["updated_at"] = datetime.now(contract_timezone(contract["timezone"])).isoformat(timespec="seconds")
    task_manifest["files"] = scan_version_files(task_root / version, task_manifest_path)
    write_json(task_manifest_path, task_manifest)
    return {"zip": str(output), "manifest": str(manifest_path), "zip_sha256": sha256(output), "file_count": len(files)}


def validate(args: argparse.Namespace) -> dict[str, Any]:
    contract = load_contract()
    task_root = args.task_root.expanduser().resolve()
    index = load_index(task_root, contract)
    errors: list[str] = []
    for version in index["versions"]:
        if not re.fullmatch(contract["version_pattern"], version):
            errors.append(f"版本名无效:{version}")
            continue
        version_root = task_root / version
        for phase in contract["phases"]:
            if not (version_root / phase).is_dir():
                errors.append(f"缺少目录:{version}/{phase}")
        try:
            version_manifest(task_root, version)
        except RuntimeError as error:
            errors.append(str(error))
        delivery_pattern = re.compile(
            rf"^{re.escape(index['task_id'])}_.+_{re.escape(version)}\.[A-Za-z0-9]+$"
        )
        for delivery_file in (version_root / "04_交付").rglob("*"):
            if delivery_file.is_file() and not delivery_pattern.fullmatch(delivery_file.name):
                errors.append(f"正式交付文件名无效:{version}:{delivery_file.name}")
        for archive_path in (version_root / "06_打包").glob("*.zip"):
            try:
                with zipfile.ZipFile(archive_path) as archive:
                    names = archive.namelist()
                    if not any(name.endswith("/交付清单.json") for name in names):
                        errors.append(f"ZIP缺少交付清单:{archive_path.name}")
                    for name in names:
                        pure = PurePosixPath(name)
                        if pure.is_absolute() or ".." in pure.parts:
                            errors.append(f"ZIP路径非法:{archive_path.name}:{name}")
            except zipfile.BadZipFile:
                errors.append(f"ZIP损坏:{archive_path.name}")
    if index["current_version"] not in index["versions"]:
        errors.append("当前版本不在版本列表")
    return {"ok": not errors, "task_id": index["task_id"], "errors": errors}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="创建和校验洋葱角色任务产物目录")
    sub = root.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--code", required=True)
    create.add_argument("--title", required=True)
    create.add_argument("--business-line", choices=("app", "lead"))
    create.add_argument("--project-root", type=Path)
    create.set_defaults(handler=create_task)
    version = sub.add_parser("new-version")
    version.add_argument("--task-root", type=Path, required=True)
    version.set_defaults(handler=new_version)
    finish = sub.add_parser("finalize")
    finish.add_argument("--task-root", type=Path, required=True)
    finish.add_argument("--version")
    finish.add_argument("--status", choices=("draft", "pending_review", "accepted", "delivered"), required=True)
    finish.set_defaults(handler=finalize)
    pack = sub.add_parser("package")
    pack.add_argument("--task-root", type=Path, required=True)
    pack.add_argument("--version")
    pack.set_defaults(handler=package)
    check = sub.add_parser("validate")
    check.add_argument("--task-root", type=Path, required=True)
    check.set_defaults(handler=validate)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        result = args.handler(args)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok", True) else 2
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
