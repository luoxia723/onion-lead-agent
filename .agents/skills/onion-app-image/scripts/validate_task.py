#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED = (
    "schema_version", "task_id", "copy_source", "approved_copy_ids", "config_status",
    "placements", "asset_references", "ui_required", "ui_references", "candidate_count",
    "paid_generation_approved", "publishing_allowed",
)


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED:
        if field not in data:
            errors.append(f"missing_field:{field}")
    if data.get("schema_version") != "onion_app_image_task_v1":
        errors.append("schema_version_invalid")
    if data.get("config_status") != "saved":
        errors.append("config_not_saved")
    if not data.get("approved_copy_ids"):
        errors.append("approved_copy_required")
    if not data.get("placements"):
        errors.append("placement_required")
    if data.get("ui_required") is True and not data.get("ui_references"):
        errors.append("ui_reference_required")
    if not isinstance(data.get("candidate_count"), int) or data.get("candidate_count", 0) < 1:
        errors.append("candidate_count_invalid")
    if not isinstance(data.get("paid_generation_approved"), bool):
        errors.append("paid_approval_must_be_boolean")
    if data.get("publishing_allowed") is not False:
        errors.append("publishing_must_be_false")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", type=Path)
    args = parser.parse_args()
    data = json.loads(args.task.read_text(encoding="utf-8"))
    errors = validate(data)
    if errors:
        print("\n".join(errors))
        return 1
    print("app_image_task_valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
