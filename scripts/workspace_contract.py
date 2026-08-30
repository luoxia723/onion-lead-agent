from __future__ import annotations

import re


RUNTIME_STATE_DIRECTORY = ".runtime"
UPDATE_STATUS_PATH = ".runtime/update-status.json"
SYSTEM_BACKUP_PATH = ".runtime/system-backups"
VENV_PATH = ".runtime/venv"
SYSTEM_MANAGED_RUNTIME_PATHS = (
    UPDATE_STATUS_PATH,
    SYSTEM_BACKUP_PATH,
    VENV_PATH,
)

SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def parse_semver(value: str) -> tuple[tuple[int, int, int], tuple[str, ...] | None]:
    match = SEMVER_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(f"无法识别版本号：{value}")
    core = tuple(int(part) for part in match.group(1, 2, 3))
    prerelease = tuple(match.group(4).split(".")) if match.group(4) else None
    return core, prerelease


def prerelease_is_newer(local: tuple[str, ...], remote: tuple[str, ...]) -> bool:
    for local_part, remote_part in zip(local, remote):
        if local_part == remote_part:
            continue
        local_numeric = local_part.isdigit()
        remote_numeric = remote_part.isdigit()
        if local_numeric and remote_numeric:
            return int(remote_part) > int(local_part)
        if local_numeric != remote_numeric:
            return not remote_numeric
        return remote_part > local_part
    return len(remote) > len(local)


def remote_version_is_newer(local: str, remote: str) -> bool:
    local_core, local_prerelease = parse_semver(local)
    remote_core, remote_prerelease = parse_semver(remote)
    if remote_core != local_core:
        return remote_core > local_core
    if local_prerelease is None:
        return False
    if remote_prerelease is None:
        return True
    return prerelease_is_newer(local_prerelease, remote_prerelease)
