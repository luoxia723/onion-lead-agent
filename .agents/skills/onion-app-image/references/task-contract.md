# APP 图片生成任务合同

```json
{
  "schema_version": "onion_app_image_task_v1",
  "task_id": "与request_id相同",
  "copy_source": "APP_拍题精学_APP图片投放文案_v001.md",
  "approved_copy_ids": ["文案 1"],
  "config_status": "saved",
  "placements": [{"channel": "信息流", "placement": "...", "form": "单图"}],
  "asset_references": [],
  "ui_required": false,
  "ui_references": [],
  "candidate_count": 3,
  "paid_generation_approved": false,
  "publishing_allowed": false
}
```

`placements`为兼容现有下游继续保留数组结构，但一个任务版本必须且只能包含1项。配置页和保存端都不得接受多版位。

配置卡、Prompt生成和`validate-only`阶段允许`paid_generation_approved=false`。正式执行前本字段必须为真，同时调用命令必须显式带`--approved-in-current-task`；历史任务合同不能替代当前授权。本合同永远不允许投放发布。
