# 刀码漫剧 V3.12 Agent 执行治理

本次基线为 `05303d2`。入口位于「AI 总导演 → Agent 执行治理」。六阶段 24 步的定义继续使用 `frontend/src/router/workflow.ts`。

## 操作

1. 先在「创作向导 → 立项与指挥」保存完整制作规格。准备一份有正文的小说、剧本或分集，或准备使用同一规格的已批准 Guardian 故事圣经和时间轴。
2. 在「Agent 执行治理」选择工作流、对应固定版本和制作目标，保存运行草稿。核对角色职责和固定输入，填写意见后点「批准并排队」。
3. 查看每步状态、进度、尝试、耗时或报错。依赖失败时，修正故障后点击「重试失败步骤」。成功的角色结果会被复用。要终止等待或执行中的工作，使用「取消 Agent 运行」。
4. 全部完成后展开角色结果，核对输入与输出哈希，填写意见。可点「确认 Agent 输出」或「退回 Agent 输出」。审阅记录固定到本次输出；如需改输入、调整目标或重新审阅，创建一次新运行。

| 工作流 | 执行顺序 | 输出 |
| --- | --- | --- |
| 原稿筹备 | 总导演 → 剧情分析 → 编剧 | 制作目标和规格摘要、段落与字数、供人工编辑的原文分集段落 |
| 生产预检 | 总导演 → 美术设计 → 分镜导演 → 镜头审核 → 后期制作 | 角色场景和风格依据、分集镜头时长、Guardian 合同与问题、时间轴素材哈希核验 |

这两条流程使用本机规则和现有校验。原稿草案由段落和字数规则整理，语义改写需要人工或后续已授权的模型。生产预检复用已批准的 Guardian 合同、连续性报告、时间轴和素材校验。历史运行保留固定版本；重新批准另一套计划后，旧计划会受到既有生产失效规则约束。审核结论属于运行记录，素材和正式创作版本通过原业务审批入口管理。Codex 官方执行、模型驱动的自主分工、真实图片及动态视频生成仍待开发。

## 持久化与执行

- `0018` 新增 PostgreSQL `agent_runs`。项目和请求键唯一；草稿记录规格、原稿或生产资产的固定版本、输入 SHA-256 和规则版本。显式审批后，通过现有 `tasks`、`task_attempts` 和 `task_events` 执行和记录步骤。审批与步骤入队同事务提交。
- 各步骤验证固定输入，按任务依赖执行并记录上一步哈希。审核核对连贯的步骤输出 SHA-256。Worker 租约中断沿用已有恢复机制，以及既有单机并发和尝试上限。
- 两个工作流的允许外部预算均为 0。正数预算请求被拒绝，操作只读取项目输入和本机素材。Agent 不建立模型账本消费记录。

## 实际验收

- 后端 **170 项通过，0 失败，0 跳过**，耗时 302.40 秒。有一条现有 Starlette/httpx 弃用提示。Agent 专项覆盖审批前队列为空、幂等、跨项目拒绝、规格和原稿改版后仍读取历史固定输入、交接哈希异常拒审、取消、Worker 租约过期恢复和局部重试。Vue 类型检查、Vite 生产构建和 Alembic 模型比对通过。 [后端 JUnit](v3-12-agent-backend.xml)
- Chrome 在总导演工作台完成原稿筹备的草稿、审批、三个角色执行、结果复核和刷新。生产预检完成五个角色步骤，核验了固定规格 v2 和 36 帧方形时间轴的实际素材。两条流程均保存审核结果，外部费用为 0。 [原稿筹备截图](v3-12-agent-story.png) · [原稿筹备记录](v3-12-agent-story-browser.json) · [生产预检截图](v3-12-agent-preflight.png) · [生产预检记录](v3-12-agent-preflight-browser.json)
- 固定规格流程继续完成 FFmpeg 720×720 候选、成片技术质检、授权和 ZIP 文件哈希核对，错误画幅和发行地域被拦截。Chrome 回归覆盖 12 个工作区导航及六阶段 24 步。Guardian 两集十镜实测返工一镜、复用九镜，核验 30 张交付证据帧，缺失或同体积篡改被阻断。 [固定规格与交付](v3-12-production-spec-browser.json) · [导航和 Guardian](v3-12-legacy-browser.json)
- 本机升级前备份，并在独立 PostgreSQL、独立文件目录核对 7 个项目、13 项素材和 120 个文件，实际回读视频 Range 为 206；独立库演练 `0017 → 0018 → 0017 → 0018`。本机随后升级到 `0018`，新版页面、Agent 接口及 Worker 可用，真实模型开关关闭、预算 0、已发真实请求 0。 [恢复和迁移](v3-12-recovery.json) · [本机运行状态](v3-12-readiness.json)

## 源码与复验

- `backend/app/agent_runs.py`、`agent_tools.py`、`models.py`、`main.py`、`worker.py` 与 `backend/migrations/versions/0018_agent_runs.py` 实现工作流、持久化和 Worker 调用。
- `frontend/src/pages/DirectorPage.vue` 与 `frontend/src/components/production/AgentRuns.vue` 提供输入、审批、状态和审核界面。
- `backend/tests/test_agent_runs.py`、`scripts/browser-v3-agent.mjs` 与 `scripts/browser-v3-spec.mjs` 覆盖专项用例。现有健康检查和恢复脚本同步升级到 `0018`。

```powershell
npm.cmd --prefix frontend run build
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --junitxml data/tmp/v3-agent-backend.xml
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-agent --browser-evidence data/tmp/v3-agent-qa
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-spec --browser-evidence data/tmp/v3-agent-qa
& ./.venv/Scripts/python.exe scripts/p6_recovery_check.py --stage agent-runs
```

## 回滚

等待队列空闲并备份当前数据库和文件，然后运行 `scripts/stop.ps1`。若 `agent_runs` 为空，在 `backend` 运行 `..\.venv\Scripts\alembic.exe downgrade 0017`，回退本次 Git 提交并重建前端，再用 `scripts/start.ps1 -Production` 启动。若已有 Agent 运行记录，迁移会拒绝直接删表。保留当前数据库及文件，将 `0017` 升级前的配对数据库与文件快照恢复到独立环境，并使用 `05303d2` 构建和启动该环境。验收后切换配置；保存回滚前的数据，以便核对或再次前进迁移。
