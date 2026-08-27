# 洋葱线索 Agent 项目规则

## 项目身份

本仓库是由投放AI内容自动化主仓库自动生成的 `lead` 角色工作区。发行版本 `0.1.2`，来源提交 `1bdae5f9c70d69deecd04457ab2490f0fea56390`。本仓库不是Skill源码owner；`AGENTS.md`、`.agents/`、`产品资料/`、`.codex/`、`scripts/`和发行清单只能通过上游自动更新，不在本仓库手工修改。

## 角色职责

负责消费已确认线索购买动因、服务与权益事实和可选创意报告，生成线索口播和两类混剪。不重新生成需求报告、创意报告、购买动因或功能方向。

本角色包含：

- `onion-lead-video-copy`
- `onion-voiceover-video-mix`
- `onion-talking-head-video-mix`

## 工具权限

策略、APP和线索角色连接同一个 `onion-agent` OAuth MCP，均可使用情报库全部只读、素材库全部只读和生成服务。角色差异只在Skill与工作流。维护写入、数据库、SSH和对象存储管理不在本仓库。

## 更新

用户说“更新项目”“拉取最新”或相近表达时：

1. 运行 `git status --short`，只检查系统维护区是否被修改；
2. 系统维护区有改动时停止并说明，不覆盖用户修改；
3. 使用 `git pull --ff-only`，禁止reset、clean、checkout覆盖和force操作；
4. 更新后运行 `python scripts/doctor.py --offline`；
5. 不移动、不删除、不改写用户工作区中的任何既有文件。

## 文件所有权

- 系统维护区：`AGENTS.md`、`README.md`、`.agents/`、`产品资料/`、`.codex/`、`scripts/`、`VERSION`、`发行信息.json`、`角色清单.json`；
- 用户工作区：`工作区/输入/`、`工作区/产物/`、`工作区/草稿/`、`工作区/审核/`、`工作区/缓存/`和`.runtime/`；
- 用户工作区被Git忽略，更新不得进入这些目录；
- API密钥、OAuth Token、数据库连接、SSH私钥和对象存储凭据不得写入仓库或产物。

## 运行

执行某个Skill前必须完整读取`.agents/skills/<skill-name>/SKILL.md`及其直接引用。付费、上传、写入和媒体生成继续执行Skill规定的当前任务确认门禁。所有正式产物写入`工作区/产物/`，不得写回`.agents/`。
