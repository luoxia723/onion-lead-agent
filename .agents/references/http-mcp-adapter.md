# 当前统一 OAuth MCP 适配

本文件是正式 Skill 与当前已部署工具之间的可替换适配层。Skill 的输入事实、业务判断和停止条件仍是权威；工具名、运输和返回字段以后变化时修改本适配，不反向降低 Skill 要求。机器清单见 [HTTP MCP 适配合同](http-mcp-adapter.json)。

## 唯一连接

- 服务名：`onion-agent`；
- Streamable HTTP MCP：`https://intel-mcp.guanghexinzhi.cn/agent/mcp`；
- 认证：OAuth 2.1 授权码＋PKCE；
- 权限：`intelligence:external:read`、`intelligence:internal-performance:read`、`materials:read`、`generation:use`；
- 下游只在首次连接时输入管理员一对一签发的一次性激活 Token；OAuth 凭据由 Codex 保存，不进入项目仓库；
- 不再要求下游配置情报、素材、Kimi、KIE、Mossland、Qwen ASR、TOS、数据库或 SSH 密钥。

家庭网络仍通过团队代理命中正式 HTTPS 白名单。业务 Skill 不直连数据库、SSH、腾讯 COS 或火山 TOS，不改走旧本地网关。`materials_prepare_sources` 返回火山 TOS 短时读取地址；历史字段名 `cos_object_key` 只是稳定对象键的兼容名，不表示再调腾讯 COS。

## 工具范围

统一入口原合同代理 12 个 `intelligence_*` 和 5 个 `materials_*` 只读工具，另提供：

- `intelligence_freeze_report_input`；
- `generation_upload_media`；
- `generation_kimi_generate`；
- `generation_kie_image`；
- `generation_prepare_image_delivery`；
- `generation_moss_tts`；
- `generation_qwen_asr`；
- `generation_render_voiceover_video`；
- `generation_render_talking_head_video`；
- `generation_get_output`。

数据响应仍分别符合 `intelligence_mcp_v3` 和 `materials_mcp_v2`。工具集可以新增，当前 Skill 所需工具、字段、分页、scope 和回源语义不能缺失。

## 通用门禁

- 执行前确认当前任务真实发现了所需工具；只有配置文件而工具未进入任务时停止并要求刷新客户端。
- 生成工具必须传 `approved_in_current_task=true` 和本次唯一 `idempotency_key`。用户在当前任务明确要求生成、配音、ASR 或渲染即可视为当前授权；只是预览计划或 dry-run 时不得传真。
- `idempotency_key` 绑定任务、工具、输入指纹和用户意图。网络重试复用原 Key；用户明确要求新版才创建新 Key；原请求失败后不自动换 Key 重扣费用。
- 生成产物返回高熵 `output_id`、SHA-256 和短时下载地址。立即下载到当前用户产物目录并校验哈希；不把短时 URL 写成长期产物引用。
- 模型、生图、配音、ASR 和自动 QA 成功不代表人工审核通过。

## 报告路由

四份报告必须按 [四份报告上下文与 Token 合同](report-context-efficiency.md) 调用一次`intelligence_freeze_report_input`，由服务器消费全部页面、验证版本与守恒并返回私有快照ZIP。外层模型只读紧凑manifest；ZIP下载到`.runtime`并校验哈希后才由确定性脚本展开，不得逐页将MCP正文插入对话。

### `onion-demand-report`

`intelligence_list_report_availability` 选择 demand 采集批次 → `intelligence_get_report_scope` 冻结 → 完整分页 `intelligence_list_demand_evidence` → 按需用 `intelligence_get_analysis_evidence`、`intelligence_get_material_detail` 回查。

### `onion-creative-report`

`intelligence_list_report_availability` 盘点 creative 批次 → `intelligence_get_report_scope` 冻结 → 完整分页 `intelligence_list_creative_evidence` → 按 `material_context_id` 归并案例 → `intelligence_get_material_detail` 批量回查必需详情。

### 两份内部报告

先用 `intelligence_list_report_availability` 确认共同周期，再共用一份完整分页 `intelligence_list_internal_complete_material_pool` 冻结快照。第一页冻结 `dataset_version`，后续页必须一致；版本变化时从第一页重取。`intelligence_list_internal_material_evidence` 只复核高表现交集，不替代完整池。

`dashboard_path` 必须解析为 `https://toufang-ai.guanghexinzhi.cn/content-dashboard?...` 绝对地址并通过详情 API 回查。外部详情规范参数为`content_id`；统一Agent冻结层会把上游历史`material_context_id`改写为`content_id`，工作台仍兼容旧报告。内部详情固定为`business=app|lead＋internal_snapshot_id＋view=analysis`。分页中断、数据版本变化、稳定总数不守恒或 `coverage_status=partial` 时，保留真实缺口并按各 Skill 规则停止或降级。

## 素材与生成路由

### 纯配音混剪

`generation_moss_tts` 生成最终旁白 → `generation_qwen_asr` 取真实时间轴 → `materials_search_segments(retrieval_mode=hybrid)` 批量建立候选 → `materials_get_segments` 回查稳定 ID → `materials_prepare_sources` 为终选签发短时源 → `generation_render_voiceover_video` 渲染。正文不生成、烧录或内嵌字幕；一条已有前贴可作为完整有声前置源传给同一渲染工具。

### 口播主轴混剪

`materials_search_speech_masters(business_line=app|lead)` → `materials_get_speech_master(expected_business_line=同一值)` → `materials_prepare_sources` 取母片；静音配画按与纯配音相同的 `hybrid` 路由选择和回查。完整计划通过 `generation_render_talking_head_video` 渲染，可同时传真实字幕时间轴和一条完整有声前贴；工具返回 MP4 和 ASS 字幕产物。对应业务线母片为 0 时停止素材库流程，不跨业务线借母片。

### APP 图片

配置卡、Prompt、参考图顺序和 `--validate-only` 仍由 Skill 本地确定。参考图按SHA-256去重后先通过`generation_upload_media`各上传一次；付费生成调`generation_kie_image`并按清单顺序传`reference_output_ids`，不在每个job重复传base64。每个渲染job使用绑定`task_id＋job_id＋清单指纹`的独立幂等Key；无参考图时省略参考字段走文生图。KIE候选立即下载并校验SHA-256；用户提交选择后，尺寸和体积处理由Skill本地Pillow脚本只对采纳图片批量执行，不调用MCP交付处理。

### APP/线索口播文案

GPT/Codex 只编排归一化上下文；使用对应 Skill 的 Kimi 系统提示词和编排后用户消息调 `generation_kimi_generate`。完整 Markdown 输出仍按原校验器检查，校验失败时复用原任务上下文发起一次明确修复，不由外层模型静默改写正文。

## 证据边界

`hybrid` 分数只表示检索相关性，不表示需求强度、创意质量或表现因果。外部互动、内部消耗、转化和模型生成成功都不能变成新广告承诺。
