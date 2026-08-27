#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import re
import secrets
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen
from uuid import UUID
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


MARKDOWN_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
EXPLICIT_ANCHOR = re.compile(r'<a\s+id=["\']([^"\']+)["\']\s*></a>', re.IGNORECASE)
HEADING = re.compile(r"(?m)^#{1,6}\s+(.+?)\s*$")
WORKBENCH_HOST = "toufang-ai.guanghexinzhi.cn"


def heading_slug(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value)
    text = re.sub(r"[`*_~]", "", text).strip().lower()
    text = re.sub(r"[^\w\-\u3400-\u9fff\s]", "", text)
    return re.sub(r"[\s-]+", "-", text).strip("-")


def markdown_anchors(text: str) -> set[str]:
    anchors = {html.unescape(value).strip() for value in EXPLICIT_ANCHOR.findall(text)}
    anchors.update(filter(None, (heading_slug(value) for value in HEADING.findall(text))))
    return anchors


def validate_workbench_url(value: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.netloc != WORKBENCH_HOST:
        return ["工作台链接必须使用正式HTTPS域名"], warnings
    if parsed.path != "/content-dashboard":
        return ["工作台链接路径必须为/content-dashboard"], warnings
    query: dict[str, list[str]] = {}
    for pair in parsed.query.split("&"):
        if not pair:
            continue
        key, _, raw = pair.partition("=")
        query.setdefault(unquote(key), []).append(unquote(raw))
    external_keys = [key for key in ("content_id", "material_context_id") if query.get(key)]
    internal = query.get("internal_snapshot_id", [])
    if len(external_keys) + bool(internal) != 1:
        errors.append("工作台链接必须且只能指定一个外部或内部详情身份")
        return errors, warnings
    if external_keys:
        key = external_keys[0]
        values = query[key]
        if len(values) != 1:
            errors.append(f"工作台{key}必须唯一")
        else:
            try:
                UUID(values[0])
            except ValueError:
                errors.append(f"工作台{key}不是UUID")
        if key == "material_context_id":
            warnings.append("外部详情使用兼容参数material_context_id；新链接优先使用content_id")
    else:
        if len(internal) != 1:
            errors.append("工作台internal_snapshot_id必须唯一")
        else:
            try:
                UUID(internal[0])
            except ValueError:
                errors.append("工作台internal_snapshot_id不是UUID")
        if query.get("business") not in (["app"], ["lead"]):
            errors.append("内部详情business必须唯一且为app或lead")
        if query.get("view") != ["analysis"]:
            errors.append("内部详情必须指定view=analysis")
    return errors, warnings


def check_markdown_links(path: Path, *, project_root: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    warnings: list[str] = []
    checked = 0
    workbench = 0
    workbench_urls: list[str] = []
    for label, raw_target in MARKDOWN_LINK.findall(text):
        target = html.unescape(raw_target.strip())
        checked += 1
        if target.startswith("#"):
            anchor = unquote(target[1:])
            if anchor not in markdown_anchors(text):
                errors.append(f"{path.name}:缺少文档锚点:{anchor}")
            continue
        parsed = urlsplit(target)
        if parsed.scheme in {"http", "https"}:
            if parsed.netloc == WORKBENCH_HOST:
                workbench += 1
                workbench_urls.append(target)
                url_errors, url_warnings = validate_workbench_url(target)
                errors.extend(f"{path.name}:{label}:{value}" for value in url_errors)
                warnings.extend(f"{path.name}:{label}:{value}" for value in url_warnings)
            elif parsed.netloc in {"example.com", "www.example.com"}:
                errors.append(f"{path.name}:正式文档保留示例链接:{target}")
            elif not parsed.netloc:
                errors.append(f"{path.name}:外部链接缺少域名:{target}")
            continue
        if parsed.scheme:
            errors.append(f"{path.name}:不支持的链接协议:{target}")
            continue
        relative = Path(unquote(parsed.path))
        resolved = (path.parent / relative).resolve()
        try:
            resolved.relative_to(project_root.resolve())
        except ValueError:
            errors.append(f"{path.name}:相对链接越出项目:{target}")
            continue
        if not resolved.is_file():
            errors.append(f"{path.name}:相对链接文件不存在:{target}")
            continue
        if parsed.fragment and resolved.suffix.lower() == ".md":
            target_text = resolved.read_text(encoding="utf-8")
            if unquote(parsed.fragment) not in markdown_anchors(target_text):
                errors.append(f"{path.name}:目标文档缺少锚点:{target}")
    return {
        "path": str(path),
        "checked": checked,
        "workbench": workbench,
        "workbench_urls": workbench_urls,
        "errors": errors,
        "warnings": warnings,
    }


def online_workbench_check(value: str, *, timeout: int) -> str | None:
    parsed = urlsplit(value)
    query = {}
    for pair in parsed.query.split("&"):
        key, _, raw = pair.partition("=")
        query[unquote(key)] = unquote(raw)
    external_id = query.get("content_id") or query.get("material_context_id")
    if external_id:
        endpoint = f"https://{WORKBENCH_HOST}/api/external/contents/{external_id}"
        expected_path = ("content", "content_id")
        expected_value = external_id
    else:
        business = query.get("business", "")
        snapshot_id = query.get("internal_snapshot_id", "")
        endpoint = f"https://{WORKBENCH_HOST}/api/internal/{business}/snapshots/{snapshot_id}"
        expected_path = ("snapshot", "internal_snapshot_id")
        expected_value = snapshot_id
    try:
        request = Request(endpoint, headers={"Accept": "application/json", "User-Agent": "onion-artifact-link-check/1"})
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return f"详情API返回HTTP {response.status}:{value}"
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as error:
        return f"详情API不可达:{value}:{error}"
    current: Any = payload
    for key in expected_path:
        current = current.get(key) if isinstance(current, dict) else None
    if str(current or "") != expected_value:
        return f"详情API身份不一致:{value}:returned={current}"
    return None


def check_links(args: argparse.Namespace) -> dict[str, Any]:
    root = find_project_root(args.project_root)
    target = args.path.expanduser().resolve()
    paths = [target] if target.is_file() else sorted(target.rglob("*.md"))
    if not paths:
        raise RuntimeError("没有可校验的Markdown文件")
    rows = [check_markdown_links(path, project_root=root) for path in paths]
    online_errors: list[str] = []
    online_count = 0
    if args.online_workbench:
        urls = sorted({url for row in rows for url in row["workbench_urls"]})
        online_count = len(urls)
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.online_concurrency) as pool:
            results = list(pool.map(lambda url: online_workbench_check(url, timeout=args.timeout), urls))
        for error in results:
            if error:
                online_errors.append(error)
    return {
        "ok": not any(row["errors"] for row in rows) and not online_errors,
        "file_count": len(rows),
        "link_count": sum(row["checked"] for row in rows),
        "workbench_link_count": sum(row["workbench"] for row in rows),
        "online_workbench_count": online_count,
        "errors": [error for row in rows for error in row["errors"]] + online_errors,
        "warnings": [warning for row in rows for warning in row["warnings"]],
    }


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


def safe_business_text(value: str, *, fallback: str = "未命名", max_length: int = 64) -> str:
    text = re.sub(r'[\\/:*?"<>|\r\n\t]+', "-", value.strip())
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[-_]{2,}", "_", text).strip(" .-_")
    return (text or fallback)[:max_length].rstrip(" .-_") or fallback


def readable_stem(title: str, label: str, business_line: str | None) -> str:
    prefix = {"app": "APP", "lead": "线索"}.get(business_line or "", "")
    parts = [value for value in (prefix, safe_business_text(title), label) if value]
    return "_".join(parts)


def available_task_root(parent: Path, base_name: str) -> Path:
    candidate = parent / base_name
    if not candidate.exists():
        return candidate
    for number in range(2, 100):
        candidate = parent / f"{base_name}_{number:02d}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("同名业务任务目录过多，请使用更具体的业务主题")


def create_version(
    task_root: Path,
    version: str,
    contract: dict[str, Any],
    *,
    task_id: str,
    title: str,
    business_line: str | None,
) -> dict[str, Any]:
    paths = version_paths(task_root, version, contract)
    for path in paths.values():
        Path(path).mkdir(parents=True, exist_ok=False)
    now = datetime.now(contract_timezone(contract["timezone"])).isoformat(timespec="seconds")
    manifest = {
        "schema_version": "onion_artifact_task_version_v1",
        "task_id": task_id,
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
    file_stem = readable_stem(args.title, info["label"], args.business_line)
    directory_base = f"{file_stem}_{now.strftime('%H%M%S')}"
    task_root = available_task_root(
        root / contract["workspace_root"] / date_dir / info["category"],
        directory_base,
    )
    task_root.mkdir(parents=True, exist_ok=False)
    version = create_version(
        task_root,
        "v001",
        contract,
        task_id=task_id,
        title=args.title,
        business_line=args.business_line,
    )
    index = {
        "schema_version": "onion_artifact_task_index_v1",
        "task_id": task_id,
        "artifact_code": args.code,
        "artifact_label": info["label"],
        "naming_version": 2,
        "directory_name": task_root.name,
        "file_stem": file_stem,
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
        suggested = f"{file_stem}_v001.{extension}"
    return {
        "task_root": str(task_root),
        "task_id": task_id,
        "directory_name": task_root.name,
        "file_stem": file_stem,
        "suggested_primary_file": suggested,
        **version,
    }


def load_index(task_root: Path, contract: dict[str, Any]) -> dict[str, Any]:
    path = task_root / "任务索引.json"
    if not path.is_file():
        raise RuntimeError("任务目录缺少任务索引.json")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "onion_artifact_task_index_v1":
        raise RuntimeError("任务索引版本无效")
    if not re.fullmatch(contract["task_id_pattern"], str(value.get("task_id") or "")):
        raise RuntimeError("任务ID不符合合同")
    if value.get("naming_version") == 2:
        if value.get("directory_name") != task_root.name:
            raise RuntimeError("任务目录名与任务索引不一致")
        if not str(value.get("file_stem") or "").strip():
            raise RuntimeError("任务索引缺少业务可读文件名")
    else:
        if value["task_id"] != task_root.name:
            raise RuntimeError("旧任务目录名与任务ID不一致")
        value.setdefault("file_stem", f"{value['task_id']}_{value['artifact_label']}")
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
        task_id=index["task_id"],
        title=index["title"],
        business_line=index.get("business_line"),
    )
    index["versions"].append(version)
    index["current_version"] = version
    write_json(task_root / "任务索引.json", index)
    extension = contract["artifact_types"][index["artifact_code"]].get("primary_extension")
    suggested = f"{index['file_stem']}_{version}.{extension}" if extension else None
    return {
        "task_root": str(task_root),
        "task_id": index["task_id"],
        "file_stem": index["file_stem"],
        "suggested_primary_file": suggested,
        **result,
    }


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
    stem = f"{index['file_stem']}_交付包_{version}"
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
    root_name = f"{index['file_stem']}_{version}"
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
    warnings: list[str] = []
    project_root = find_project_root(args.project_root)
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
            rf"^{re.escape(index['file_stem'])}(?:_.+)?_{re.escape(version)}\.[A-Za-z0-9]+$"
        )
        for delivery_file in (version_root / "04_交付").rglob("*"):
            if delivery_file.is_file() and not delivery_pattern.fullmatch(delivery_file.name):
                errors.append(f"正式交付文件名无效:{version}:{delivery_file.name}")
            if delivery_file.is_file() and delivery_file.suffix.lower() == ".md":
                link_result = check_markdown_links(delivery_file, project_root=project_root)
                errors.extend(link_result["errors"])
                warnings.extend(link_result["warnings"])
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
    return {"ok": not errors, "task_id": index["task_id"], "errors": errors, "warnings": warnings}


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
    check.add_argument("--project-root", type=Path)
    check.set_defaults(handler=validate)
    links = sub.add_parser("check-links")
    links.add_argument("--path", type=Path, required=True)
    links.add_argument("--project-root", type=Path)
    links.add_argument("--online-workbench", action="store_true")
    links.add_argument("--timeout", type=int, default=15)
    links.add_argument("--online-concurrency", type=int, choices=range(1, 17), default=8)
    links.set_defaults(handler=check_links)
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
