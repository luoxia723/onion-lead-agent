#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


REQUIRED = ("schema_version", "task_id", "business_line", "copy_id", "copy_sha256", "composition_mode", "retrieval_mode", "execution_mode", "voiceover", "front_hook", "sentence_units", "shots", "output", "publishing_allowed")


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED:
        if field not in data:
            errors.append(f"missing_field:{field}")
    if data.get("schema_version") != "onion_voiceover_mix_plan_v1":
        errors.append("schema_version_invalid")
    if data.get("business_line") not in {"app", "lead"}:
        errors.append("business_line_invalid")
    if data.get("composition_mode") != "voiceover_montage":
        errors.append("composition_mode_invalid")
    if data.get("retrieval_mode") != "hybrid":
        errors.append("retrieval_mode_invalid")
    if data.get("execution_mode") not in {"local_render", "formal"}:
        errors.append("execution_mode_invalid")
    if "subtitles" in data:
        errors.append("subtitles_forbidden")
    if data.get("publishing_allowed") is not False:
        errors.append("publishing_must_be_false")
    if data.get("copy_sha256") and not re.fullmatch(r"[0-9a-f]{64}", str(data["copy_sha256"])):
        errors.append("copy_sha256_invalid")
    units = data.get("sentence_units", [])
    if not units:
        errors.append("sentence_units_required")
    else:
        for index, unit in enumerate(units):
            if unit.get("start_ms") is None or unit.get("end_ms") is None or unit.get("end_ms", 0) <= unit.get("start_ms", 0):
                errors.append(f"sentence_{index}:invalid_timeline")
            if index and unit.get("start_ms") != units[index - 1].get("end_ms"):
                errors.append(f"sentence_{index}:timeline_not_continuous")
    unit_ids = {unit.get("id") for unit in units}
    covered_unit_ids: set[str] = set()
    for index, shot in enumerate(data.get("shots", [])):
        if shot.get("sentence_id") not in unit_ids:
            errors.append(f"shot_{index}:unknown_sentence")
        else:
            covered_unit_ids.add(str(shot.get("sentence_id")))
        if shot.get("source_audio_mode") != "mute":
            errors.append(f"shot_{index}:body_source_must_be_muted")
        if shot.get("timeline_end_ms", 0) <= shot.get("timeline_start_ms", 0):
            errors.append(f"shot_{index}:invalid_timeline")
        if shot.get("source_sha256") and not re.fullmatch(r"[0-9a-f]{64}", str(shot["source_sha256"])):
            errors.append(f"shot_{index}:source_sha256_invalid")
    for unit_id in unit_ids - covered_unit_ids:
        errors.append(f"sentence_without_shot:{unit_id}")
    front = data.get("front_hook")
    if front is not None and front.get("source_audio_mode") != "keep":
        errors.append("front_hook_audio_must_be_kept")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    args = parser.parse_args()
    errors = validate(json.loads(args.plan.read_text(encoding="utf-8")))
    if errors:
        print("\n".join(errors))
        return 1
    print("voiceover_mix_plan_valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
