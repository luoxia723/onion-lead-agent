#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def codex_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get("CODEX_BIN", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    discovered = shutil.which("codex")
    if discovered:
        candidates.append(Path(discovered))
    if sys.platform == "darwin":
        candidates.extend(
            (
                Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
                Path.home() / "Applications/ChatGPT.app/Contents/Resources/codex",
            )
        )
    elif os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        program_files = Path(os.environ.get("ProgramFiles", ""))
        if str(local):
            candidates.extend(
                (
                    local / "Programs/ChatGPT/resources/codex.exe",
                    local / "Programs/ChatGPT/Resources/codex.exe",
                )
            )
            candidates.extend(
                sorted(local.glob("ChatGPT/app-*/resources/codex.exe"), reverse=True)
            )
        if str(program_files):
            candidates.extend(
                (
                    program_files / "ChatGPT/resources/codex.exe",
                    program_files / "ChatGPT/Resources/codex.exe",
                )
            )
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def resolve_codex_binary(*, required: bool = True) -> Path | None:
    for candidate in codex_candidates():
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    if required:
        raise RuntimeError(
            "未找到Codex CLI。请在角色项目中说“初始化项目环境”；"
            "桌面端已安装时会优先复用其自带codex，不要求安装Node.js。"
        )
    return None
