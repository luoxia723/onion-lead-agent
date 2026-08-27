# 口播主轴混剪计划合同

```json
{
  "schema_version": "onion_talking_head_mix_plan_v2",
  "task_id": "...",
  "business_line": "app",
  "source": {
    "source_kind": "library",
    "source_reference": "...",
    "source_sha256": "...",
    "presentation_type": "real_person",
    "classified_business_line": "app"
  },
  "cta_check": {
    "final_cta_text": "...",
    "final_cta_start_ms": 38000,
    "final_cta_end_ms": 42000,
    "cta_kind": "app_download",
    "compatible": true,
    "verification_basis": "母片结尾明确引导下载APP"
  },
  "retrieval_mode": "hybrid",
  "execution_mode": "server_render",
  "batch_subject_mode": "same_speaker_variants",
  "base_video": {"file": "...", "sha256": "...", "duration_ms": 42000},
  "speech_segments": [{"id": "S001", "text": "...", "start_ms": 0, "end_ms": 2500}],
  "front_hook": null,
  "overlays": [
    {"speech_segment_id": "S002", "start_ms": 5000, "end_ms": 8200, "source_id": "...", "source_sha256": "...", "source_start_ms": 1000, "source_end_ms": 4200, "source_audio_mode": "mute", "semantic_similarity_score": 0.72, "lexical_score": 0.5, "matched_lexical_terms": ["拍题", "步骤"], "retrieval_score": 0.68, "selection_reason": "..."}
  ],
  "subtitles": [],
  "output": {"width": 720, "height": 1280, "fps": 24},
  "publishing_allowed": false
}
```

APP与线索使用同一合同，`business_line`只允许`app`或`lead`。`source`与`cta_check`替代旧的独立入口记录。前贴存在时记录来源、文件、哈希、时长和`source_audio_mode=keep`。工具返回字段进入计划前映射到这一合同。

`execution_mode`固定为`server_render`。素材库母片传短时URL；用户提供母片或前贴传`generation_upload_media`返回的`output_id`。字幕项必须含`text`、`start_ms`和`end_ms`，无重叠且不越出母片时长。
