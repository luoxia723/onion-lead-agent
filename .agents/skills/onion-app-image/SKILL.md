---
name: onion-app-image
description: 当用户已经确认 APP 图片文案并要求生成信息流、应用商店或学习机正式图片时使用；打开本地配置卡，通过统一OAuth MCP的KIE GPT Image 2生成候选，完成品牌与UI门禁、规格处理、人工选择和采纳图片交付。不要用于撰写图片文案、修改已有广告图、线索九宫格或投放发布。
---

# APP 图片生成

> 业务状态：2026-08-26按旧正式Skill直接复用并完成当前仓库迁移。配置卡、102条版位规则、KIE异步任务与断点恢复、批量渲染、Logo/IP/字体资产、规格处理、候选选择和采纳打包均已恢复；除非xhh明确重新开启讨论，不重做业务流程。具体付费生图仍按当前任务逐次授权。

> 执行适配：业务流程不变；KIE Key、参考图上传、异步任务和结果暂存已收口到统一OAuth MCP，下游不再配置供应商Key。

## 产物

把已确认图片文案转成可选择、可追溯的图片候选，并只把用户采纳的图片作为正式交付。当前只做“确认文案 → 配置卡 → KIE直接生图”，不做已有图片编辑或同款复刻。

## 运行前读取

- [统一任务产物目录与命名合同](../../references/artifact-layout.md)
- [统一 OAuth MCP 适配](../../references/http-mcp-adapter.md)
- [输入、输出与人工门禁](references/input-output-contract.md)
- [渠道与版位](references/channel-placement.md)
- [视觉与Prompt规则](references/prompt-rules.md)
- [合规视觉雷区](references/visual-compliance.md)
- [KIE生图合同](references/provider-contract.md)
- [压缩与导出](references/export-rules.md)
- [任务合同](references/task-contract.md)
- [渲染清单合同](references/render-manifest.md)

## 必需输入

- 已确认的 APP 图片文案；
- 产品事实与品牌资产；
- 渠道、版位、图片形式、套数、Logo/IP/字体/CTA/UI等制作配置；
- 需要可识别 UI 时的真实产品截图；
- 用户对候选数量和付费生成的当前确认。

正式生图调用统一 `onion-agent` OAuth MCP 的`generation_kie_image`。下游项目不读取、不保存也不要求用户填写KIE Key。

## 固定流程

1. 确认输入是已批准的固定格式APP图片文案；把每套的渠道、图片形式、主标题/副标题或短句整理为配置卡上下文。
2. 建立“产品事实→目标人群→具体场景→产品动作→可感知变化”的最小视觉链。
3. 启动`scripts/interactive_server.py`，显式把统一任务版本的`02_过程`作为`--output-dir`，并打开返回的本地配置卡。一次任务只能选择一个具体版位；即使聊天中已经说过参数，也必须由用户保存配置结果。
4. 需要可识别APP/UI时等待用户上传真实截图；缺失时停止或改为不可识别的抽象屏幕。
5. 根据配置结果与[Prompt规则](references/prompt-rules.md)生成`image-render-manifest.json`；逐张写清文案、场景、产品动作、构图、参考资产、安全区和禁止项。
6. 运行`scripts/validate_task.py`和每个任务的`scripts/render.py --validate-only`，只验证清单、Prompt、比例、引用顺序和输出路径，不调用付费接口；同时确认角色项目`.runtime/venv`可导入Skill锁定的Pillow，缺失时先运行项目环境初始化，不能等用户采纳后才发现无法交付。
7. 告知预计图组数和图片数；只有取得当前任务付费确认后才进入生成。先按SHA-256去重本任务的Logo、IP、风格、字体和UI参考图；每个唯一资产只调一次`generation_upload_media`，传明确的`file_name`、`mime_type`和不带`data:`前缀的`base64_data`，并保留返回的`output_id`。再按`image-render-manifest.json`的job顺序调`generation_kie_image`，传Prompt、版位比例和已上传参考图的`reference_output_ids`；无参考图时省略该字段走文生图。上传Key绑定`task_id＋资产SHA-256`，每张候选的生图Key分别绑定`task_id＋job_id＋清单指纹`，两个job禁止共用一个Key。两类调用都传`approved_in_current_task=true`和[统一OAuth MCP适配](../../references/http-mcp-adapter.md)要求的`generation_context`：参考资产使用独立上传批次和去重资产序号，KIE使用当前候选批次总job数、job_id和清单顺序；默认单批不超过12个KIE逻辑job，用户明确确认时管理上限20。网络重试复用各自原Key；明确终态失败只由服务器重试对应job；状态不明时回查`generation_get_operation`并停止新建，不整批重跑。
8. 将工具返回的候选PNG立即下载到清单的`output`路径，校验`sha256`和MIME，并在`image-render-result.json`保留`job_id`、`output_id`、哈希、供应商taskId和人工状态；不保存短时URL作为长期引用。回执与本地文件一致即记为候选，不在选择前处理尺寸或体积。文字、Logo、UI、事实、构图和审美检查只记录为候选提示，不得据此中断同一批已授权job、自动淘汰图片或重新付费生成。完成当前授权批次后运行`scripts/build_selection_page.py`，把全部技术成功的候选交给用户查看。
9. 用户结合候选图和检查提示直接选择“采纳”或“不采纳”，两种决定都不要求填写理由或反馈。选择结果保存后直接运行`scripts/prepare_accepted_deliveries.py`，一次读取全部`accepted_schemes`，使用本地Pillow按已保存版位的精确尺寸和KB上限生成JPEG、校验并写入`04_交付`与`05_质检`；零采纳同样正常完成，本地处理不按图片数再次向用户授权。用户明确要求打包时，才把交付规格质检结果传给`scripts/package_accepted_images.py --delivery-result <路径>`，生成ZIP和交付清单到`06_打包`。
10. 任务根目录、版本、文件名和包名由`scripts/artifact_workspace.py`创建与校验；`.runtime/<任务ID>/`只保存可重建过程文件，不上传广告平台、不发布。

## 核心边界

- 文案必须逐字使用确认稿，生图模型不能改写产品事实或 CTA。
- 没有真实 UI 截图时，不生成可识别的虚构界面。
- 参考图必须标明 Logo、IP、字体、UI、风格或构图角色；不把旧广告图当编辑基准。
- 一个任务版本只允许一个具体版位。配置页使用单选，保存端也必须拒绝多个`placement_ids`；`placements`继续保留数组结构但长度固定为1。
- 多套图片可以换场景、人物、构图和视觉隐喻，不能改变文案核心与功能事实。
- 付费生成、外部上传和写对象存储需要当前任务授权。
- 旧任务文件里的`paid_generation_approved=true`不能替代当前任务命令上的`--approved-in-current-task`。
- KIE提交结果不确定时保留任务状态并停止，不能再次创建可能重复扣费的任务。
- 生成后内容检查按[输入、输出与人工门禁](references/input-output-contract.md)只作为候选提示，不中断已授权批次、不自动淘汰或重做。
- 下游不执行`render.py`或`batch_render.py`的直连KIE付费分支；这两个脚本只保留确定性清单校验与本地后处理能力。
- 规格处理固定发生在人工选择之后，只处理采纳图片。正式流程不调用`generation_prepare_image_delivery`；本地Pillow处理次数是交付模块实现细节，不需要用户逐张授权。
- 交付打包只读取交付规格质检结果中已经校验的JPEG，不重新读取候选或重复压缩。
- 自动规格检查和内容提示都不替代人工选择；技术成功的候选全部给用户看，由用户决定是否采纳。
- 选择页只收集采纳/不采纳决定，不收集固定规则反馈、主观理由或跳过反馈状态；点击任一决定后直接进入下一个候选。
