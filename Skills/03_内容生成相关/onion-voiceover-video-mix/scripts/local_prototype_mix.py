#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


COPY_RE = re.compile(
    r'(?ms)^<a id="copy-(\d{3})"></a>\n'
    r'^## (文案-(\d{3}))｜(.+?)\n'
    r'(.*?)(?=^<a id="copy-|\Z)'
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str]) -> None:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"command_failed:{command[0]}:{result.stderr[-2000:]}"
        )


def extract_copy(markdown: str, copy_id: str) -> tuple[str, str]:
    matches = [match for match in COPY_RE.finditer(markdown) if match.group(2) == copy_id]
    if len(matches) != 1:
        raise ValueError(f"copy_not_unique:{copy_id}")
    match = matches[0]
    body = match.group(5)
    voiceover = re.search(
        r"(?ms)^### 正式口播\s*\n(.*?)(?=^### 使用依据)", body
    )
    if voiceover is None:
        raise ValueError("formal_voiceover_missing")
    text = re.sub(r"\s+", "", voiceover.group(1))
    if not text:
        raise ValueError("formal_voiceover_empty")
    return match.group(4).strip(), text


def split_subtitle_units(text: str, *, maximum_chars: int = 28) -> list[str]:
    pieces = [
        item.strip()
        for item in re.findall(r"[^，。！？；：,.!?;]+[，。！？；：,.!?;]?", text)
        if item.strip()
    ]
    units: list[str] = []
    for piece in pieces:
        while len(piece) > maximum_chars:
            units.append(piece[:maximum_chars])
            piece = piece[maximum_chars:]
        if piece:
            if units and len(piece) < 7 and len(units[-1]) + len(piece) <= maximum_chars:
                units[-1] += piece
            else:
                units.append(piece)
    return units


def classify_intent(text: str) -> str:
    if re.search(r"学情报告|学习数据|掌握情况|学习趋势|提升建议|薄弱", text):
        return "report"
    if re.search(r"AI定制班|学习计划|每天的小任务|追踪进度|推进到", text):
        return "ai_plan"
    return "scene"


def probe_duration_ms(path: Path) -> int:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return round(float(result.stdout.strip()) * 1000)


def allocate_times(units: list[str], duration_ms: int) -> list[tuple[int, int]]:
    weights = [max(1, len(re.sub(r"\W", "", item))) for item in units]
    total = sum(weights)
    boundaries = [0]
    cumulative = 0
    for weight in weights[:-1]:
        cumulative += weight
        boundaries.append(round(duration_ms * cumulative / total))
    boundaries.append(duration_ms)
    return list(zip(boundaries[:-1], boundaries[1:], strict=True))


def normalized_filter() -> str:
    return (
        "[0:v]fps=24,split=2[bg0][fg0];"
        "[bg0]scale=720:1280:force_original_aspect_ratio=increase,"
        "crop=720:1280,boxblur=20:2,eq=brightness=-0.16:saturation=0.86[bg];"
        "[fg0]scale=720:1280:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[v]"
    )


def select_sources(
    units: list[str], manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    pools: dict[str, list[dict[str, Any]]] = {}
    for item in manifest["segments"]:
        pools.setdefault(str(item["intent"]), []).append(item)
    counters = {key: 0 for key in pools}
    selected = []
    for unit in units:
        intent = classify_intent(unit)
        pool = pools.get(intent) or pools.get("scene") or []
        if not pool:
            raise ValueError(f"source_pool_empty:{intent}")
        item = pool[counters.get(intent, 0) % len(pool)]
        counters[intent] = counters.get(intent, 0) + 1
        selected.append(item)
    return selected


def render(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = args.output_dir.resolve()
    audio_dir = output_dir / "02_配音与时间轴"
    plan_dir = output_dir / "04_混剪计划"
    final_dir = output_dir / "05_成片与质检"
    for directory in (audio_dir, plan_dir, final_dir):
        directory.mkdir(parents=True, exist_ok=True)
    temp_dir = final_dir / ".local-mix-tmp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()

    copy_path = args.copy_file.resolve()
    markdown = copy_path.read_text(encoding="utf-8")
    title, voiceover_text = extract_copy(markdown, args.copy_id)
    copy_sha256 = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    manifest = json.loads(args.sources_manifest.read_text(encoding="utf-8"))
    if manifest.get("retrieval_mode") != "hybrid":
        raise ValueError("sources_manifest_retrieval_mode_must_be_hybrid")

    supplied_audio = args.voiceover_audio.resolve()
    if not supplied_audio.is_file():
        raise ValueError("mossland_voiceover_audio_missing")
    final_audio = audio_dir / f"voiceover-final{supplied_audio.suffix.lower()}"
    if supplied_audio != final_audio:
        shutil.copy2(supplied_audio, final_audio)
    duration_ms = probe_duration_ms(final_audio)

    units = split_subtitle_units(voiceover_text)
    times = allocate_times(units, duration_ms)
    selected_sources = select_sources(units, manifest)

    base_cache: dict[str, Path] = {}
    shot_paths: list[Path] = []
    sentence_units = []
    shots = []
    for index, (text, timing, source) in enumerate(
        zip(units, times, selected_sources, strict=True), start=1
    ):
        start_ms, end_ms = timing
        unit_id = f"S{index:03d}"
        segment_id = str(source["segment_id"])
        source_path = Path(source["source_local_file_path"]).resolve()
        if sha256_file(source_path) != source["content_hash"]:
            raise ValueError(f"source_hash_mismatch:{segment_id}")
        base_clip = base_cache.get(segment_id)
        if base_clip is None:
            base_clip = temp_dir / f"base-{segment_id}.mp4"
            clip_duration = (int(source["end_ms"]) - int(source["start_ms"])) / 1000
            run([
                "ffmpeg", "-y", "-ss", f"{int(source['start_ms']) / 1000:.3f}",
                "-t", f"{clip_duration:.3f}", "-i", str(source_path),
                "-filter_complex", normalized_filter(), "-map", "[v]", "-an",
                "-r", "24", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "21", "-pix_fmt", "yuv420p", str(base_clip),
            ])
            base_cache[segment_id] = base_clip
        shot_path = temp_dir / f"shot-{index:03d}.mp4"
        shot_duration = max(0.05, (end_ms - start_ms) / 1000)
        run([
            "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(base_clip),
            "-t", f"{shot_duration:.3f}", "-an", "-r", "24",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", str(shot_path),
        ])
        shot_paths.append(shot_path)
        role = classify_intent(text)
        sentence_units.append({
            "id": unit_id, "text": text, "start_ms": start_ms,
            "end_ms": end_ms, "role": role,
            "requires_product_visual": role in {"report", "ai_plan"},
        })
        shots.append({
            "sentence_id": unit_id,
            "timeline_start_ms": start_ms,
            "timeline_end_ms": end_ms,
            "source_id": segment_id,
            "source_sha256": source["content_hash"],
            "source_start_ms": int(source["start_ms"]),
            "source_end_ms": int(source["end_ms"]),
            "source_local_file_path": str(source_path),
            "source_audio_mode": "mute",
            "looped_for_local_prototype": shot_duration * 1000 > (
                int(source["end_ms"]) - int(source["start_ms"])
            ),
            "selection_reason": source["selection_reason"],
        })

    concat_list = temp_dir / "concat.txt"
    concat_list.write_text(
        "".join(f"file '{path}'\n" for path in shot_paths), encoding="utf-8"
    )
    visual_path = temp_dir / "visual.mp4"
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i",
        str(concat_list), "-c", "copy", str(visual_path),
    ])

    output_video = final_dir / "output-local-prototype.mp4"
    run([
        "ffmpeg", "-y", "-i", str(visual_path), "-i", str(final_audio),
        "-map", "0:v:0", "-map", "1:a:0", "-r", "24",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
        "-shortest", "-movflags", "+faststart", str(output_video),
    ])

    plan = {
        "schema_version": "onion_voiceover_mix_plan_v1",
        "task_id": args.task_id,
        "business_line": args.business_line,
        "copy_id": args.copy_id,
        "copy_sha256": copy_sha256,
        "composition_mode": "voiceover_montage",
        "retrieval_mode": "hybrid",
        "execution_mode": "local_render",
        "voiceover": {
            "file": str(final_audio), "sha256": sha256_file(final_audio),
            "duration_ms": duration_ms, "provider": "Mossland",
        },
        "front_hook": None,
        "sentence_units": sentence_units,
        "shots": shots,
        "output": {"width": 720, "height": 1280, "fps": 24},
        "publishing_allowed": False,
        "title": title,
    }
    plan_path = plan_dir / "mix-plan-local-prototype.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
            "-of", "json", str(output_video),
        ],
        check=True, capture_output=True, text=True,
    )
    decode = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(output_video), "-f", "null", "-"],
        check=False, capture_output=True, text=True,
    )
    qa = {
        "status": "local_render_pending_manual_review",
        "video_sha256": sha256_file(output_video),
        "mix_plan_sha256": sha256_file(plan_path),
        "ffprobe": json.loads(probe.stdout),
        "decode_passed": decode.returncode == 0,
        "limitations": [
            "句段时间由真实音频总时长按字符比例近似分配",
            "宽松匹配允许循环候选片段，待人工完整听看",
            "视频不生成、烧录或内嵌字幕",
        ],
    }
    qa_path = final_dir / "qa-local-prototype.json"
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(temp_dir)
    return {
        "video": str(output_video), "plan": str(plan_path),
        "qa": str(qa_path), "duration_ms": duration_ms,
        "sentence_unit_count": len(sentence_units),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("copy_file", type=Path)
    parser.add_argument("--copy-id", default="文案-001")
    parser.add_argument("--business-line", choices=["app", "lead"], required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--sources-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--voiceover-audio", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(render(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
