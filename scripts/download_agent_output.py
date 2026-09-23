#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable
import urllib.error
import urllib.request
from urllib.parse import urlsplit


ALLOWED_HOST = "intel-mcp.guanghexinzhi.cn"
OUTPUT_PATH = re.compile(r"^/agent/outputs/[A-Za-z0-9_-]{16,128}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CHUNK_SIZE = 1024 * 1024


class DownloadError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retry_after: float | None = None,
        transient: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after
        self.transient = transient


def validate_download_url(url: str, *, error_code: str) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise DownloadError(
            error_code,
            "下载地址不是已登记的统一 Agent 短时产物地址",
        ) from error
    valid = (
        parsed.scheme == "https"
        and parsed.hostname == ALLOWED_HOST
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and bool(OUTPUT_PATH.fullmatch(parsed.path))
    )
    if not valid:
        raise DownloadError(
            error_code,
            "下载地址不是已登记的统一 Agent 短时产物地址",
        )


def normalized_mime_type(value: str | None) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()


def _download_once(
    *,
    url: str,
    output: Path,
    expected_sha256: str,
    expected_byte_count: int,
    expected_mime_type: str | None = None,
    timeout_seconds: int = 300,
    open_request: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    validate_download_url(url, error_code="invalid_download_url")
    digest = expected_sha256.strip().lower()
    if not SHA256.fullmatch(digest):
        raise DownloadError("invalid_sha256", "期望 SHA-256 必须是64位十六进制")
    if expected_byte_count <= 0:
        raise DownloadError("invalid_byte_count", "期望文件大小必须大于0")
    expected_mime = normalized_mime_type(expected_mime_type)

    target = output.expanduser().resolve()
    if target.exists():
        raise DownloadError("output_already_exists", "目标文件已存在，拒绝覆盖")
    if not target.parent.is_dir():
        raise DownloadError("output_parent_missing", "目标目录不存在")

    request = urllib.request.Request(
        url,
        headers={
            "Accept": expected_mime or "application/octet-stream, */*",
            "User-Agent": "onion-role-output-downloader/1",
        },
        method="GET",
    )
    try:
        response = open_request(request, timeout=timeout_seconds)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise DownloadError(
                "download_access_denied",
                "下载入口拒绝访问；不要重新认证 MCP，请保留 output_id 并交给维护者检查",
            ) from error
        if error.code in (404, 410):
            raise DownloadError(
                "output_not_found_or_expired",
                "产物不存在或短时地址已过期；不要用新幂等键重复付费生成",
            ) from error
        if error.code == 429 or 500 <= error.code <= 599:
            raise DownloadError(
                "download_http_error",
                f"下载入口返回 HTTP {error.code}",
                retry_after=parse_retry_after((error.headers or {}).get("Retry-After")),
                transient=True,
            ) from error
        raise DownloadError("download_http_error", f"下载入口返回 HTTP {error.code}") from error
    except (OSError, urllib.error.URLError, TimeoutError) as error:
        raise DownloadError("download_network_error", "下载请求未完成") from error

    temporary: Path | None = None
    try:
        with response:
            validate_download_url(
                str(response.geturl()),
                error_code="invalid_download_redirect",
            )
            actual_mime = normalized_mime_type(response.headers.get("Content-Type"))
            if expected_mime and actual_mime != expected_mime:
                raise DownloadError(
                    "mime_type_mismatch",
                    f"响应类型不匹配：expected={expected_mime}, actual={actual_mime or 'unknown'}",
                )
            raw_length = str(response.headers.get("Content-Length") or "").strip()
            if raw_length:
                try:
                    declared_length = int(raw_length)
                except ValueError as error:
                    raise DownloadError(
                        "invalid_content_length",
                        "下载响应的 Content-Length 无效",
                    ) from error
                if declared_length != expected_byte_count:
                    raise DownloadError(
                        "byte_count_mismatch",
                        f"响应大小不匹配：expected={expected_byte_count}, actual={declared_length}",
                    )

            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.",
                suffix=".part",
                dir=target.parent,
            )
            temporary = Path(temporary_name)
            actual_digest = hashlib.sha256()
            actual_count = 0
            with os.fdopen(descriptor, "wb") as handle:
                while True:
                    try:
                        chunk = response.read(CHUNK_SIZE)
                    except (OSError, http.client.HTTPException) as error:
                        raise DownloadError(
                            "download_network_error",
                            "下载连接在文件传输完成前中断",
                        ) from error
                    if not chunk:
                        break
                    actual_count += len(chunk)
                    if actual_count > expected_byte_count:
                        raise DownloadError(
                            "byte_count_mismatch",
                            f"下载内容超过期望大小：expected={expected_byte_count}",
                        )
                    actual_digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())

            if actual_count != expected_byte_count:
                raise DownloadError(
                    "byte_count_mismatch",
                    f"文件大小不匹配：expected={expected_byte_count}, actual={actual_count}",
                )
            actual_sha256 = actual_digest.hexdigest()
            if actual_sha256 != digest:
                raise DownloadError(
                    "sha256_mismatch",
                    "文件 SHA-256 与 MCP 回执不一致",
                )
            try:
                os.link(temporary, target)
            except FileExistsError as error:
                raise DownloadError(
                    "output_already_exists",
                    "目标文件已存在，拒绝覆盖",
                ) from error
            temporary.unlink()
            temporary = None
            return {
                "status": "downloaded",
                "output": str(target),
                "byte_count": actual_count,
                "sha256": actual_sha256,
                "mime_type": actual_mime,
            }
    except DownloadError:
        raise
    except OSError as error:
        raise DownloadError("local_io_error", "本地文件写入失败") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(0.0, (date - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def download_agent_output(
    *,
    url: str,
    output: Path,
    expected_sha256: str,
    expected_byte_count: int,
    expected_mime_type: str | None = None,
    timeout_seconds: int = 300,
    open_request: Callable[..., Any] = urllib.request.urlopen,
    max_attempts: int = 3,
    max_retry_wait_seconds: float = 60,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Retry only transient transport failures; integrity and permanent errors fail closed."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if max_retry_wait_seconds < 0:
        raise ValueError("max_retry_wait_seconds must not be negative")
    waited_seconds = 0.0
    for attempt in range(max_attempts):
        try:
            return _download_once(
                url=url,
                output=output,
                expected_sha256=expected_sha256,
                expected_byte_count=expected_byte_count,
                expected_mime_type=expected_mime_type,
                timeout_seconds=timeout_seconds,
                open_request=open_request,
            )
        except DownloadError as error:
            retryable = error.code == "download_network_error" or (
                error.code == "download_http_error" and error.retry_after is not None
            )
            retryable = retryable or error.transient
            if not retryable or attempt + 1 >= max_attempts:
                raise
            delay = error.retry_after if error.retry_after is not None else min(2**attempt, 8)
            if delay > max_retry_wait_seconds - waited_seconds:
                raise DownloadError(
                    error.code,
                    f"{error}; Retry-After exceeds the {max_retry_wait_seconds:g}s retry wait budget",
                    retry_after=error.retry_after,
                    transient=error.transient,
                ) from error
            sleep(delay)
            waited_seconds += delay
    raise AssertionError("unreachable")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="下载并校验统一 Agent 返回的短时产物；请求不会携带 OAuth 凭据"
    )
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--byte-count", type=int, required=True)
    parser.add_argument("--mime-type")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = download_agent_output(
            url=args.url,
            output=args.output,
            expected_sha256=args.sha256,
            expected_byte_count=args.byte_count,
            expected_mime_type=args.mime_type,
            timeout_seconds=args.timeout_seconds,
        )
    except DownloadError as error:
        print(
            json.dumps(
                {"status": "error", "error_code": error.code, "message": str(error)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
