#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


REQUIRED = (
    "schema_version",
    "task_id",
    "business_line",
    "source",
    "cta_check",
    "retrieval_mode",
    "batch_subject_mode",
    "base_video",
    "speech_segments",
    "front_hook",
    "overlays",
    "subtitles",
    "output",
    "publishing_allowed",
)


def _is_sha256(value: object) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", str(value or "")))


def _valid_interval(start: object, end: object, *, upper: int | None = None) -> bool:
    if not isinstance(start, int) or not isinstance(end, int):
        return False
    if start < 0 or end <= start:
        return False
    return upper is None or end <= upper


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED:
        if field not in data:
            errors.append(f"missing_field:{field}")
    if data.get("schema_version") != "onion_talking_head_mix_plan_v2":
        errors.append("schema_version_invalid")
    business_line = data.get("business_line")
    if business_line not in {"app", "lead"}:
        errors.append("business_line_invalid")
    source = data.get("source")
    if not isinstance(source, dict):
        errors.append("source_invalid")
        source = {}
    if source.get("source_kind") not in {"library", "provided"}:
        errors.append("source_kind_invalid")
    if not source.get("source_reference"):
        errors.append("source_reference_required")
    if not _is_sha256(source.get("source_sha256")):
        errors.append("source_sha256_invalid")
    if source.get("presentation_type") not in {"real_person", "digital_human"}:
        errors.append("presentation_type_invalid")
    classified_line = source.get("classified_business_line")
    if classified_line not in {"app", "lead", "unknown"}:
        errors.append("classified_business_line_invalid")
    if source.get("source_kind") == "library" and classified_line != business_line:
        errors.append("library_business_line_mismatch")
    cta = data.get("cta_check")
    if not isinstance(cta, dict):
        errors.append("cta_check_invalid")
        cta = {}
    if cta.get("cta_kind") not in {
        "app_download",
        "lead_capture",
        "neutral",
        "none",
        "conflict",
    }:
        errors.append("cta_kind_invalid")
    if cta.get("compatible") is not True:
        errors.append("cta_not_compatible")
    if not cta.get("verification_basis"):
        errors.append("cta_verification_basis_required")
    cta_start = cta.get("final_cta_start_ms")
    cta_end = cta.get("final_cta_end_ms")
    if (cta_start is None) != (cta_end is None):
        errors.append("cta_timeline_incomplete")
    elif cta_start is not None and not _valid_interval(cta_start, cta_end):
        errors.append("cta_timeline_invalid")
    if data.get("retrieval_mode") != "hybrid":
        errors.append("retrieval_mode_invalid")
    if data.get("batch_subject_mode") not in {None, "same_speaker_variants", "multiple_speakers"}:
        errors.append("batch_subject_mode_invalid")
    if data.get("publishing_allowed") is not False:
        errors.append("publishing_must_be_false")
    base_video = data.get("base_video")
    if not isinstance(base_video, dict):
        errors.append("base_video_invalid")
        base_video = {}
    if not _is_sha256(base_video.get("sha256")):
        errors.append("base_video_sha256_invalid")
    duration_ms = base_video.get("duration_ms", 0)
    if not isinstance(duration_ms, int) or duration_ms <= 0:
        errors.append("base_video_duration_invalid")
        duration_ms = 0
    segments = data.get("speech_segments", [])
    if not segments:
        errors.append("speech_segments_required")
    segment_ids: set[object] = set()
    previous_end = -1
    for index, segment in enumerate(segments):
        segment_id = segment.get("id")
        if not segment_id or segment_id in segment_ids:
            errors.append(f"speech_segment_{index}:id_invalid")
        segment_ids.add(segment_id)
        start = segment.get("start_ms", -1)
        end = segment.get("end_ms", -1)
        if not _valid_interval(start, end, upper=duration_ms or None):
            errors.append(f"speech_segment_{index}:timeline_invalid")
        if isinstance(start, int) and start < previous_end:
            errors.append(f"speech_segment_{index}:overlap")
        if isinstance(end, int):
            previous_end = max(previous_end, end)
    overlays = sorted(data.get("overlays", []), key=lambda item: item.get("start_ms", 0))
    for index, overlay in enumerate(overlays):
        if overlay.get("speech_segment_id") not in segment_ids:
            errors.append(f"overlay_{index}:unknown_speech_segment")
        if overlay.get("source_audio_mode") != "mute":
            errors.append(f"overlay_{index}:source_must_be_muted")
        start = overlay.get("start_ms", 0)
        end = overlay.get("end_ms", 0)
        if not _valid_interval(start, end, upper=duration_ms or None):
            errors.append(f"overlay_{index}:invalid_timeline")
        previous_overlay_end = (
            overlays[index - 1].get("end_ms", 0) if index else 0
        )
        if (
            index
            and isinstance(start, int)
            and isinstance(previous_overlay_end, int)
            and start < previous_overlay_end
        ):
            errors.append(f"overlay_{index}:overlap")
        if not _is_sha256(overlay.get("source_sha256")):
            errors.append(f"overlay_{index}:source_sha256_invalid")
        if not _valid_interval(
            overlay.get("source_start_ms"), overlay.get("source_end_ms")
        ):
            errors.append(f"overlay_{index}:source_timeline_invalid")
        for field in (
            "semantic_similarity_score",
            "lexical_score",
            "matched_lexical_terms",
            "retrieval_score",
        ):
            if field not in overlay:
                errors.append(f"overlay_{index}:missing_retrieval_evidence:{field}")
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
    print("talking_head_mix_plan_valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
