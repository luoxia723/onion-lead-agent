# 四份报告上下文与 Token 合同

## 目的

四份报告必须完整取得 MCP 事实，但原始分页响应不应进入外层 Agent 对话。业务逻辑、字段、守恒和报告格式保持不变；本合同只改变数据怎样进入模型。

## 固定链路

```text
一次冻结范围
→ 统一MCP服务器完成全部分页与版本校验
→ 返回私有快照ZIP、下载并校验SHA-256
→ 原始记录展开到 .runtime 私有快照
→ 按稳定记录 ID 计算内容哈希和增量
→ 只把本报告需要的紧凑事实送入隔离模型任务
→ 模型只输出语义映射或报告正文
→ 确定性脚本计数、渲染和校验
```

## 强制规则

1. 不允许由外层 Agent 逐页调用 MCP、阅读页面正文后再请求下一页。
2. 固定调用一次`intelligence_freeze_report_input`。服务器只向外层返回记录数、页数、SHA、完整度和快照产物；下载ZIP后用`.agents/scripts/extract_report_input_snapshot.py`校验并展开。下游不配置MCP Bearer Token。
3. MCP 的 transport envelope、每页 applied filters、重复 scope 和游标不进入模型输入；快照保留每条业务记录全部字段。
4. 同一个内部完整素材池快照同时供内部需求和内部创意使用；不得为两份报告重复分页。
5. 模型任务不继承当前长对话。使用只含目标 Skill、直接合同、本次运行参数和紧凑证据包的隔离上下文。
6. 原始快照不能在模型多轮对话中重复插入。首次语义提取后只传稳定 ID、语义字段、中心/边界样本和必要统计。
7. 同一周期有前版快照时先比较逐记录哈希：未变化记录复用已验收语义映射；新增、变更和删除记录进入增量复核。模型 bundle 同时维护语义哈希与完整报告事实哈希；只有消耗、排名、高表现状态或链接变化时重算统计和代表案例，不重复运行需求/创意语义归并。复用不能跳过最终全局中心/边界检查和守恒校验。
8. 不默认逐条回查全部详情。冻结证据不足以完成六维判断的候选、中心/边界样本和最终代表案例，可以在一个程序化阶段批量补取详情；返回仍写入私有快照，不进入外层上下文。
9. 角色任务的快照、模型请求、响应、usage和回执写入`.runtime/<机器任务ID>/报告上下文/`；主仓维护者历史/原型任务可继续使用`.runtime/策略Agent产物/`。两者都不写入Git，也不作为正式交付目录。
10. 任一分页不守恒、数据版本变化、快照摘要变化或映射校验失败时停止，不退回外层手工拼接 MCP 返回。
11. 已有同一冻结输入的正式验收报告时，不允许模型整篇重写。先用 `.agents/scripts/reuse_validated_report.py` 锁定报告、语义哈希和完整报告事实哈希；内部需求使用语义运行 `receipt.json` 的标准化单元和最终映射摘要。语义指纹与报告事实哈希都完全相同时才直接复用原报告并重新运行校验器，模型调用数必须为0。只有语义变化时进入局部重分析；只有消耗、排名、高表现状态、标题或链接变化时不重跑语义模型，但必须确定性重渲染，不能复制旧统计。试验稿复用后仍是试验稿，不能因复用回执升级为正式报告。
12. 四类报告不得分别手工执行复制、校验和打包。唯一候选写入`03_候选`后使用统一`report-delivery`进入`pending_review`；只有当前用户明确人工采用后，才使用`report-accept --approved-in-current-task`标记`accepted`并生成最终ZIP。自动校验替代不了人工业务判断，人工判断也不能跳过数据守恒、链接和产物校验。

冻结后运行 `.agents/scripts/prepare_report_model_bundle.py` 按报告字段合同生成有界批次。外部需求保留全部需求证据；外部创意按 `material_context_id` 合并同一案例的多个创意观察；内部创意只选择 `creative_analysis_eligible=true`，但原始完整池仍留在快照中。模型 bundle 的记录数、稳定 ID 和源快照 SHA 必须写入 manifest。

需要模型处理的每个有界批次通过 `.agents/scripts/run_isolated_model_task.py` 执行。只显式传目标 Skill、当前任务必需的直接合同和一个模型 batch；该命令使用临时 Codex 会话，不继承外层聊天，不允许任务内再次访问 MCP，并把 usage 与输入/输出摘要写入回执。模型调用仍须当前任务明确授权。

多批任务固定使用 map/reduce：map 只输出“稳定记录ID＋本报告语义字段＋中心/边界证据”，reduce 只读取 map 结果和必要统计。所有稳定ID必须在 map 输出中有且仅有一个处理去向。reduce 不得重新读取原始快照；报告渲染不得重新读取全部模型 batch。

将旧执行方式迁移到本合同前必须做同输入影子A/B。自由重跑若改变已确认卡片/结构数量、名称、主体或排序，优化不得切换；同输入应先锁定旧报告和语义基线。只有新范围或真实语义增量才允许产生新卡片或结构，并继续通过原Skill校验和人工验收。

## 执行

外部需求调`intelligence_freeze_report_input(mode=external-demand, report_triggered_at, evidence_start_at, evidence_end_at)`；外部创意改为`mode=external-creative`。内部两份报告共用一次`intelligence_freeze_report_input(mode=internal-complete, statistics_start_date, statistics_end_date)`。

工具成功后：

```bash
python3 .agents/scripts/extract_report_input_snapshot.py \
  .runtime/<任务>/report-input-snapshot.zip \
  --expected-sha256 <工具返回的sha256> \
  --output-dir .runtime/<任务>/冻结输入
```

快照ZIP和展开文件都是用户任务运行数据，不进入Git。

## 增量边界

逐记录哈希相同只说明 MCP 输入事实未变化。以下任一变化仍要求相关记录重跑：

- Skill 归并规则或模型任务合同变化；
- 产品标准命名源变化且影响内部需求承接；
- 高表现池规则变化；
- 已确认中心/边界样本被删除或变更；
- 用户改变目标时间节点或报告范围。

这套优化不能把“旧报告结论不变”当作事实；它只避免对完全相同的记录重复做同一语义工作。
