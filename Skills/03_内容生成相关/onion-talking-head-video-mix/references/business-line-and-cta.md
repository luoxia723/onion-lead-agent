# 业务线、母片与CTA规则

## 单一流程

APP与线索不拆 Skill。`business_line`只决定素材库过滤、母片标签回查和CTA兼容判断；其余时间轴、配画、渲染和QA流程完全共用。

## 素材库母片

1. `materials_search_speech_masters`传入目标`business_line`；
2. 采用前调用`materials_get_speech_master`并传同一个`expected_business_line`；
3. MCP的`presentation_type=human`映射为计划中的`real_person`，`digital_human`保持不变；
4. 回查业务标签不同、缺少真实时间轴或缺少稳定身份时停止，不跨业务线找替代母片。

## 用户上传母片

- 记录`source_kind=provided`、本地引用和SHA-256；不自动入库；
- 识别结果可以是`app`、`lead`或`unknown`；识别为相反业务线时必须结合完整CTA复核；
- 母片原声、清洗文案与时间轴不一致时停止。

## CTA兼容

CTA类型记录为：

- `app_download`：下载、打开或搜索APP；
- `lead_capture`：报名、领取体验、咨询或提交联系方式；
- `neutral`：不指向特定转化入口；
- `none`：没有明确CTA；
- `conflict`：同一结尾同时存在无法共存的转化指令。

目标为APP时，明确的`lead_capture`不兼容；目标为线索时，明确的`app_download`不兼容。`neutral`或`none`不自动判错，但必须记录判断依据并由使用者确认是否采用。出现冲突时停止；不得通过覆盖画面、字幕或删除部分原声，伪装成另一业务线。
