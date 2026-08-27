# 洋葱线索 Agent 项目规则

## 项目身份

本仓库是由投放AI内容自动化主仓库自动生成的 `lead` 角色工作区。发行版本 `0.1.7`，来源提交 `5d99707f47827e9b348d5c042f3cb5467832c849`。本仓库不是Skill源码owner；`AGENTS.md`、`README.md`、`首次使用.md`、`.agents/`、`产品资料/`、`.codex/`、`scripts/`和发行清单只能通过上游自动更新，不在本仓库手工修改。

## 角色职责

负责消费已确认线索购买动因、服务与权益事实和可选创意报告，生成线索口播和两类混剪。不重新生成需求报告、创意报告、购买动因或功能方向。 下表就是本角色完整 Skill 集合，不另列一份重复清单。

## Skill 路由与上下文

1. 每次按用户当前要的正式产物选择一个最小Skill，只读取该SKILL.md和当前分支需要的直接引用。
2. 不因角色拥有多个Skill而预加载全部Skill，也不默认自动跑完整链路。
3. 用户已经提供并确认上游产物时直接作为交接输入，不重新生成上游。
4. 一个Skill到达人工审核或停止点后先交付；只有当前请求明确包含下一产物且授权成立时才加载下一个Skill。
5. 跨Skill只传已确认产物、稳定身份、版本、哈希和必要来源，不把上一Skill的完整长上下文继续带入。
6. 统一MCP只执行当前已选Skill的确定请求，不负责选择Skill、重做策略或绕过人工门禁。

| Skill | 何时选择 | 必要交接 | 停止点 |
|---|---|---|---|
| `onion-lead-video-copy` | 用户当前要线索留资口播文案 | 一个已选线索购买动因和信息屋；创意报告可选 | 文案人工采用 |
| `onion-voiceover-video-mix` | 用户要新旁白作为正文音频主轴的无字幕混剪 | 已确认正文；零或一条已有前贴 | 无字幕MP4和QA |
| `onion-talking-head-video-mix` | 用户要保留真人或数字人母片原声作为正文主轴 | 目标业务线、口播母片；零或一条已有前贴 | 字幕、MP4和QA |

两类视频混剪只选择一个：新旁白作为正文音频主轴时使用`onion-voiceover-video-mix`；保留真人或数字人母片原声、口型和人物主轴时使用`onion-talking-head-video-mix`。普通配画仍来自正式素材库hybrid检索。用户上传只正式支持一条完整前贴，以及口播主轴路线的一条真人/数字人母片。

`onion-ai-preroll`当前暂缓且尚未进入本角色发行。用户已有前贴时，正文未写就交给对应口播文案Skill分析承接，正文已确认就直接作为混剪可选输入；不得假装调用未发行Skill。

## 工具权限

策略、APP和线索角色连接同一个 `onion-agent` OAuth MCP，均可使用情报库全部只读、素材库全部只读和生成服务。角色差异只在Skill与工作流。维护写入、数据库、SSH和对象存储管理不在本仓库。

## 任务产物

正式产物统一写入`工作区/产物/北京时间日期/产物大类/任务ID/版本/`。执行Skill前读取`.agents/references/artifact-layout.md`，并用`scripts/artifact_workspace.py create`按Skill对应代码创建任务；修改同一任务使用`new-version`，不得覆盖旧版本。

- `01_输入`保存冻结输入或引用，`02_过程`保存计划和过程文件，`03_候选`保存未采用候选；
- `04_交付`只放正式可采用文件，文件名必须包含任务ID、产物名称和`vNNN`；
- `05_质检`保存自动与人工审核，`06_打包`保存ZIP及交付清单；
- `.runtime/<任务ID>/`只放短时下载、模型批次和可重建缓存，不得作为正式交付；
- 完成后运行`finalize`和`validate`。用户要求ZIP时运行`package`；APP图片专用打包仍可使用图片Skill脚本，但输出名、目录和ZIP内`交付清单.json`必须符合统一合同。

## 首次初始化

用户说“初始化项目环境”“首次配置”或环境检查发现缺项时：

1. 先识别系统；Windows运行`powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1 -Mode Check`，macOS运行`/bin/bash scripts/bootstrap.sh --check`；
2. 只检查或创建项目内`.runtime/venv`不需要额外确认；需要通过winget或Homebrew安装Python/Git前，先说明将修改本机软件并取得用户确认；
3. 用户确认后，Windows改用`-Mode Install`，macOS改用`--install`。能够检测但不安装系统软件时使用Windows的`-Mode Prepare`或macOS的`--prepare`；
4. 不安装Node.js、FFmpeg、Pillow、云厂商SDK或供应商Key。正式流程只需要Python 3.10+；Git只用于Pull；视频与图片规格处理都由统一MCP云端执行；
5. 后续本地Python命令优先使用项目`.runtime/venv`中的解释器。不得递归安装各Skill目录中的历史或可选`requirements.txt`；
6. 策略角色的隔离模型任务优先复用Codex桌面端自带执行器；找不到时报告具体缺口，不为此默认安装Node.js。

## 更新

用户说“更新项目”“拉取最新”或相近表达时：

1. 运行 `git status --short`，只检查系统维护区是否被修改；
2. 系统维护区有改动时停止并说明，不覆盖用户修改；
3. 使用 `git pull --ff-only`，禁止reset、clean、checkout覆盖和force操作；
4. 更新后运行 `python scripts/doctor.py --offline`；
5. 不移动、不删除、不改写用户工作区中的任何既有文件。

## 文件所有权

- 系统维护区：`AGENTS.md`、`README.md`、`首次使用.md`、`.agents/`、`产品资料/`、`.codex/`、`scripts/`、`VERSION`、`发行信息.json`、`角色清单.json`；
- 用户工作区：`工作区/输入/`、`工作区/产物/`、`工作区/草稿/`、`工作区/审核/`、`工作区/缓存/`和`.runtime/`；
- 用户工作区被Git忽略，更新不得进入这些目录；
- API密钥、OAuth Token、数据库连接、SSH私钥和对象存储凭据不得写入仓库或产物。

## 运行

按“Skill 路由与上下文”执行。付费、上传、写入和媒体生成继续遵守所选Skill的当前任务确认门禁；所有正式产物写入`工作区/产物/`，不得写回`.agents/`。
