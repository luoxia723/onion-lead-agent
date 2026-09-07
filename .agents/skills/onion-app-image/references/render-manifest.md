# APP图片渲染清单合同

`batch_render.py`读取：

```json
{
  "request_id": "...",
  "jobs": [
    {
      "job_id": "copy-001-placement-001-set-01-slot-01",
      "set_id": "copy-001-placement-001-set-01",
      "slot": 1,
      "prompt": "完整Prompt",
      "resolution": "2K",
      "size": "1280x720",
      "references": [
        {"label": "参考图1", "role": "品牌Logo", "asset_id": "...", "path": "assets/...png"}
      ],
      "output": "<任务版本目录>/03_候选/候选图片/copy-001-placement-001-set-01-01.png",
      "depends_on": []
    }
  ]
}
```

- 每个`job_id`唯一；同一套双图或三图共用`set_id`，`slot`按1、2、3排序；
- `prompt`必须逐字包含对应单图文案或当前slot的短句，不把多张文案挤进一张图；
- `resolution`固定为`2K`；`size`或`aspect_ratio`来自已保存版位配置；
- 参考图顺序固定为Logo、IP、风格/构图、字体、真实UI，缺少某类时顺延；
- Logo存在时必须是`参考图1`并满足保真Prompt；
- `output`必须位于统一任务版本的`03_候选`；短时下载和可重建缓存才进入`.runtime/<任务ID>`；重跑不覆盖不匹配的KIE任务指纹；
- 清单不能保存API Key、上传临时地址或KIE结果临时URL。
