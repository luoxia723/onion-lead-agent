# 当前 HTTP MCP 适配

本文件是正式 Skill 与当前已部署 MCP 之间的可替换适配层。各 Skill 的输入事实、业务判断和停止条件仍是权威；工具名、查询视图或返回字段以后变化时修改本文件与机器合同，不反向降低 Skill 要求。

机器可校验清单见 [HTTP MCP适配合同](http-mcp-adapter.json)。

> `0053_internal_complete_material_pool.sql`与情报 MCP `20260826T170747Z-9a19b56665cb`已部署并通过真实全量分页守恒验收；内部两份报告可以按本合同正式取数。若健康检查、工具发现、数据版本或分页守恒失败，仍必须停止。

## 连接边界

- 业务只读查询使用 Streamable HTTP MCP：
  - `onion-intelligence`：`https://intel-mcp.guanghexinzhi.cn/mcp`；
  - `onion-materials`：`https://materials-mcp.guanghexinzhi.cn/mcp`；
- Token 只从 `ONION_INTELLIGENCE_MCP_TOKEN`、`ONION_MATERIALS_MCP_TOKEN` 注入，分别携带 Codex 客户端绑定头；不得写入 Skill、仓库或产物；
- 家庭网络通过团队代理访问正式 HTTPS 白名单；业务 Skill 不改走旧 SSH stdio MCP；
- 报告和素材消费不得直接连接数据库、SSH、腾讯 COS 或火山 TOS；
- `materials_prepare_sources` 返回的是火山 TOS 短时读取地址。底层若仍保留历史字段名 `cos_object_key`，只把它视为稳定对象键兼容名，不得据此调用腾讯 COS；
- SSH 只用于采集、入库、部署、迁移等维护控制操作；素材入库的本地母片通过服务器签发的单对象短时地址直传火山 TOS，SSH 不再中转母片字节。业务 MCP 始终保持只读。

## 人员、角色与 Skill 依赖

- 每个人、每个客户端、每个 MCP 单独签发 Token，不共享 xhh、同事、Codex 与其他客户端的 Token；
- 角色工作区只分配该人员实际需要的 MCP 连接；Skill 的 `agents/openai.yaml` 声明自己依赖 `onion-intelligence` 或 `onion-materials`；
- 外部需求和外部创意报告需要 `intelligence:external:read`；内部两份报告还需要 `intelligence:internal-performance:read`；
- 两类混剪、APP/线索口播母片入口和素材入库后的回读需要 `materials:read`；
- 购买动因、功能方向、口播文案、前贴、图片文案和图片生成只消费已经确认的报告或本地产品资料，不直接分配原始情报 MCP；
- Skill 声明依赖不等于获得权限。Token scope 不足时由 HTTP MCP 返回拒绝，Skill 必须停止，不能改走SSH、数据库或其他人的 Token。

## 通用调用门禁

- 调用前确认当前任务实际发现了对应 MCP 工具；只有配置文件但工具未进入当前任务时停止并要求刷新客户端；
- 四份报告的完整分页必须通过[四份报告上下文与 Token 合同](report-context-efficiency.md)执行：由一个程序化调用或共享冻结脚本消费全部页面并写入`.runtime`，外层模型只读取manifest和后续紧凑证据包；不得逐页把MCP响应正文插入对话；
- 情报响应必须符合 `intelligence_mcp_v3`，素材响应必须符合 `materials_mcp_v2`；
- 工具集合允许增加；当前 Skill 所需工具、字段、分页、scope和回源语义不能缺失；
- 正式列表沿 `next_cursor` 读取到 `has_more=false`，Top K 搜索不能代替完整分页；
- 情报 MCP 返回的`dashboard_path`是工作台相对路径。写入正式 Markdown 前必须解析为`https://toufang-ai.guanghexinzhi.cn/content-dashboard?...`绝对地址，并至少通过详情 API 回查；不得把相对路径、旧IP或未部署的示例域名写成可点击回源链接；
- `coverage_status=partial` 时保留缺口，按 Skill 本身规则停止或降级，不能静默换周期；
- 素材检索支持`lexical`、`vector`和`hybrid`。纯配音与配画类正式调用固定使用`hybrid`：完整画面意图放`query_text`供向量召回，3～8个可直接命中的具体词放`lexical_terms`供关键词召回；服务必须返回语义分、关键词分、命中词和融合分。`/readyz`不是`vector_query=ready`或真实E2E未通过时停止；
- 检索分数只表示相关性，不表示需求强度、创意质量或表现因果。

## 策略报告路由

### `onion-demand-report`

`intelligence_list_report_availability` 选择当前可用于 demand 的采集批次 → `intelligence_get_report_scope` 冻结范围并核对只包含所选批次 → 完整分页 `intelligence_list_demand_evidence` → 代表证据按需用 `intelligence_get_analysis_evidence`、`intelligence_get_material_detail` 回查。搜索和相似工具只发现同义候选，不能决定目标时间节点适配。

### `onion-creative-report`

`intelligence_list_report_availability` 盘点 creative 批次 → `intelligence_get_report_scope` 冻结外部观察范围 → 对 video 完整分页 `intelligence_list_creative_evidence` → 按 `material_context_id` 归并完整案例 → `intelligence_get_material_detail` 取得概况、结构、分析对象、转写和媒体。搜索工具不能代替完整案例池。

### `onion-internal-demand-report`

先用`intelligence_list_report_availability`确认共同周期，再通过共享冻结脚本一次完整分页`intelligence_list_internal_complete_material_pool`取得全部原始效果记录、按稳定素材身份去重的基础素材、跨渠道比较组、零消耗、未链接、未富化、媒体异常、分析资格和高表现标记。第一页冻结`dataset_version`，后续页必须保持相同版本；MCP 返回`dataset_changed_restart_pagination`时从第一页重取。只有`demand_analysis_eligible=true`的稳定素材进入需求归并。`intelligence_list_internal_material_evidence`只用于复核高表现子集。原始记录数、基础素材数、分页唯一键和高表现子集任一不守恒时停止。相同范围和版本的快照直接与内部创意共用。

### `onion-internal-creative-report`

复用内部需求已经冻结的`intelligence_list_internal_complete_material_pool`快照；范围或版本不同时才重新分页。只把`creative_analysis_eligible=true`的稳定素材进入结构归并；原表媒体标签冲突只读取`data_quality_flags`，不覆盖稳定素材实际类型。同一素材只分析一次，从`comparison_groups`读取各平台、渠道、币种的消耗排名、高表现状态和未入池原因。`intelligence_list_internal_material_evidence`只复核高表现交集，不替代完整视频池。

## 素材路由

### `onion-voiceover-video-mix`

按最终音频句段调用`materials_search_segments(retrieval_mode=hybrid)`；完整画面意图进入`query_text`，3～8个具体词进入`lexical_terms`。服务必须证明查询Embedding与片段向量同模型就绪并返回实际`hybrid`模式、语义分、关键词分、命中词和融合分，否则停止。终选必须来自本轮候选 → `materials_get_segments` 回查全部稳定 ID → 只把终选 `content_hash` 传给 `materials_prepare_sources`。短时地址立即下载到任务缓存，计划只保存稳定 ID、源时间段、哈希和本地路径。2026-08-26正式E2E已验证三组查询同时具有非零语义分和关键词分。

### `onion-talking-head-video-mix`

单一Skill接收`business_line=app|lead`。素材库来源先`materials_search_speech_masters`固定同一`business_line` → `materials_get_speech_master`同时传`expected_business_line` → MCP `presentation_type=human`映射为计划中的`real_person`，`digital_human`保持不变；采用后用`materials_prepare_sources`取得短时源。没有对应业务线母片时允许用户上传，但不跨业务线复用素材库母片。用户上传文件的业务线与CTA检查直接写入混剪计划，不产生独立入口记录。静音配画固定走`materials_search_segments(retrieval_mode=hybrid) → materials_get_segments → materials_prepare_sources`，并使用与纯配音相同的双路检索证据、稳定ID和短时地址规则。

### `onion-material-ingest`

正式写入仍由维护者 SSH 控制服务器事务导入器和火山 TOS，不使用只读 MCP 写库。服务器只为确切 `masters/` key 签发短时 PUT 地址，本机母片直传并经服务器复核后才写库；签名 URL 不进入回执。落库完成后才通过 HTTP `onion-materials` 执行 `materials_search_segments`或`materials_get_segments`回读，并用`materials_prepare_sources`对最终验证母片做短时 Range GET。此步骤验证业务可消费性，不向 MCP 增加写权限。
