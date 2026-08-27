# 纯配音混剪计划合同

```json
{
  "schema_version": "onion_voiceover_mix_plan_v1",
  "task_id": "...",
  "business_line": "app",
  "copy_id": "文案-001",
  "copy_sha256": "...",
  "composition_mode": "voiceover_montage",
  "retrieval_mode": "hybrid",
  "execution_mode": "local_render",
  "voiceover": {"file": "...", "sha256": "...", "duration_ms": 30000},
  "front_hook": null,
  "sentence_units": [
    {"id": "S001", "text": "...", "start_ms": 0, "end_ms": 2200, "role": "开头", "requires_product_visual": false}
  ],
  "shots": [
    {"sentence_id": "S001", "timeline_start_ms": 0, "timeline_end_ms": 2200, "source_id": "...", "source_sha256": "...", "source_start_ms": 1000, "source_end_ms": 3200, "source_audio_mode": "mute", "selection_reason": "..."}
  ],
  "output": {"width": 720, "height": 1280, "fps": 24},
  "publishing_allowed": false
}
```

前贴存在时记录来源、文件、哈希、时长和`source_audio_mode=keep`。实际工具字段可以不同，但进入正式计划前必须映射到这一业务合同。

`retrieval_mode`必须为已通过readiness与真实E2E的`hybrid`。`execution_mode=local_render`表示Mossland与素材检索在外部完成，本地只做无字幕ffmpeg渲染；MP4不得包含字幕流。
