# 洋葱线索 Agent

> 统一OAuth MCP已通过部署和真实生成验收，可以按下列方式连接。

这是可直接作为Codex项目打开的 `lead` 角色仓库。

**第一次使用，请先打开 [首次使用说明](首次使用.md)。** 里面包含 Windows/macOS 通用的打开方式、Skill加载、MCP认证、Token输入位置、环境检查和常见故障处理。

打开仓库根目录并信任项目后，Codex会自动从`.agents/skills/`发现本角色Skill，并从`.codex/config.toml`读取`onion-agent` MCP地址。macOS双击根目录`连接Agent.command`、Windows双击`连接Agent.cmd`即可保持本机OAuth回调并完成连接。使用者只在浏览器认证页输入管理员发放的一次性Token；不填任何供应商API Key。

第一次打开后直接对Codex说“初始化项目环境”。Codex会按Windows/macOS选择包内脚本，检查Python、Git、项目文件和MCP配置；取得确认后可以安装缺失的Python/Git并创建项目内`.runtime/venv`。Node.js、FFmpeg和云厂商SDK不是正式角色依赖。

只读环境检查：对Codex说“运行首次环境检查”，或运行 `python scripts/first_run_check.py`。

日常只在`工作区/`中放输入、草稿、审核记录和产物。系统目录由主仓库自动更新，不要手工修改。

更新方式：使用GitHub Desktop点击Pull，或在Codex里说“更新项目到最新”。更新流程只允许fast-forward，不影响`工作区/`和`.runtime/`中的既有文件。
