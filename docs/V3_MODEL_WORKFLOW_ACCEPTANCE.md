# 刀码漫剧 V3 模型接入与制作导航

基于 `2688d2b`。按用户确认的六阶段 24 步，把已有业务入口连到项目向导和工作区提示。

## 操作

1. 在「创作向导」新建项目，把原创创意或改编目标写入项目说明。按阶段查看需要准备的材料、具体操作及预期产出。集数、时长、画风和画幅可先写入本机备注。
2. 在「AI 总导演」可引用项目说明，选择当前适用的工作流。已有本机固定时间轴渲染、整剧批次和授权交付仍通过原审批及 Worker 执行。总览和向导使用真实项目记录提示下一步。
3. 在「模型与设置 → 模型接入与预算」保存 Codex 首选模型或媒体供应商草稿。Codex 仅检查后端能否发现本机 CLI。图库、视频、云端配音及视觉质检草稿可记录模型 ID、HTTPS Base URL、区域和密钥环境变量名称。执行适配器待接入，价格未知。
4. 通过「配置文本与额度」打开文本配置。沿用 OpenAI 兼容适配器和模型预算账本。可以选择供应商模板，填写官方端点、模型名和费率，保存为禁用状态。密钥配置在本机环境变量。
5. Guardian 缺少故事圣经时，提供原稿与分集、分镜、批准故事圣经三个业务入口。已有计划的项目继续显示连续性、证据和质量审核。

## 验收

- 后端 166 项通过、0 失败、0 跳过。Vue 类型检查、Vite 生产构建、空库迁移及 Alembic 模型比对通过。保留一条 Starlette/httpx 上游弃用提示。 [JUnit](model-workflow-backend.xml)
- 隔离 Chrome 用实际 FFmpeg 素材和本机渲染验证既有工作区、深链接和多项目隔离。保存并回读 Codex 与海螺草稿，保存禁用的 OpenAI 兼容设置，打开六阶段全部 24 步，验证项目说明进入导演表单及 Guardian 缺少计划时的三个入口。 [浏览器记录](model-workflow-browser.json) · [模型页](model-workflow-models.png) · [向导](model-workflow-wizard.png) · [Guardian 缺项](model-workflow-guardian.png)
- 总导演的固定时间轴渲染、两集批次、分集返工与授权交付通过 Chrome 回归。P14 在新构建中验证诊断、键盘入口与请求来源边界。 [总导演回归](model-workflow-director.json) · [诊断回归](model-workflow-p14.json)
- 在独立数据库及存储目录还原真实 `0015` 快照，校验 7 个项目、13 项素材、120 个文件、素材 Range 206。以空配置表验证 `0015 → 0016 → 0015 → 0016`。 [恢复和迁移记录](model-workflow-recovery.json)
- 队列空闲后完成本机快照和 `0016` 升级。模型和向导页面返回 200，截图对应的项目仍可读取，Worker 在线。检测到 Codex CLI，外部模型执行与真实文本调用关闭，默认真实预算为 0。 [本机状态](model-workflow-readiness.json)

## 代码与数据

- 后端 `model_connections.py`、`models.py`、`main.py`、`overview.py` 和迁移 `0016_model_connection_drafts.py`。
- 前端 `ModelsPage.vue`、`TextProviderConfig.vue`、`WizardPage.vue`、`DirectorPage.vue`、`OverviewPage.vue`、`GuardianPage.vue`、`WorkflowContext.vue`、工作台布局、路由及类型。
- 验收 `test_model_connections.py`、迁移断言、Chrome 工作台与诊断脚本、`p6_recovery_check.py` 及对应证据。

Codex SDK/App Server 执行、专业 Agent 协作、真实模型改编与分镜、外部生成、视觉语义质检和多 Worker 扩展有待后续实现或授权验收。本轮真实模型请求和产生的外部费用均为 0。

## 复验与回滚

```powershell
npm.cmd --prefix frontend run build
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --junitxml data/tmp/model-workflow-backend.xml
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-01 --browser-evidence data/tmp/model-workflow
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-director --browser-evidence data/tmp/model-workflow-director
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase p14 --browser-evidence data/tmp/model-workflow-p14
```

回滚前等待队列空闲、备份当前数据库和文件并运行 `scripts/stop.ps1`。配置表为空时，从 `backend` 执行 `..\.venv\Scripts\alembic downgrade 0015`，回退本批提交，重新构建，在根目录运行 `scripts/start.ps1 -Production`。若已有配置，迁移会拒绝直接降级。保留当前库及文件，将升级前快照恢复到独立的数据库和存储目录，校验后切换旧版配置。
