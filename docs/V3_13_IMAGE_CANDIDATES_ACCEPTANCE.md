# 刀码漫剧 V3.13 图片候选与预算接入

基线为 `0ef4d09`。六阶段 24 步名称与顺序沿用原工作流，第 05.1 步指向图片候选区。PostgreSQL 仍为 `0018`，本轮使用已有任务、素材、规格、预算与账本表。

## 本机使用

1. 先在创作向导保存完整制作规格，再在角色与场景保存来源版本，或在故事圣经批准固定镜头。
2. 打开「AI 图片与视频 → 图片候选与内容审核」。选择用途、规格和来源版本，输入提示词，提交离线模拟。人物、场景可按历史 ID 固定版本。关键帧需要批准计划和稳定镜头 ID。
3. Worker 用 FFmpeg 解码 PNG 并验证尺寸。技术通过后，候选保留于任务目录。对照已固定参考图，在页面勾选角色身份、服装、场景或镜头要求与画风的适用项目，再保存人工审核。结果保存候选与所选参考图的哈希。
4. 通过后选择「采纳为图片素材」，在项目素材里继续使用。模拟图使用固定色块，入库记录带离线模拟标记。采纳不会修改已批准角色版本或镜头合同。要将新图片作为后续运镜的合同源图，需另存并审批对应创作版本。

OpenAI Images 适配器配置单张 PNG、固定 medium 质量。出图使用供应商原生尺寸，方图 1024×1024、竖图 1024×1536、横图 1536×1024。制作规格的 9:16 或 16:9 成片尺寸由现有运镜和剪辑流程处理。对照审核使用项目内参考图，当前适配器发送的是提示词、固定画风与制作限制。角色一致性由人工核对。 [官方 Images API 文档](https://developers.openai.com/api/reference/resources/images/methods/generate)

## 授权与结算

本阶段真实调用授权为 0 元，工作台可用模式为离线模拟。真实费用在无账单凭证时记录为未知。以下为将来获授权后的接口条件。

- 模型工作区的 OpenAI 图片配置须使用 `https://api.openai.com/v1`、获批的 GPT Image 1、1 mini 或 1.5 模型 ID 和密钥环境变量名称。密钥值留在本机环境或未入 Git 的 `.env`。
- `AI_STORY_ENABLE_PAID_IMAGE`、`AI_STORY_BUDGET_GUARD_APPROVED`、`AI_STORY_LIVE_AUTHORIZATION_ID` 以及 `AI_STORY_IMAGE_PROJECT_ID` 绑定此次授权。`AI_STORY_IMAGE_MODEL` 与 `AI_STORY_IMAGE_SECRET_ENV` 绑定模型和所用密钥变量。`AI_STORY_IMAGE_CURRENCY`、`AI_STORY_IMAGE_MAX_MICROS`、`AI_STORY_IMAGE_PRICE_SOURCE` 记录经核验的单次上限，须覆盖授权尺寸下的全部计费。额度使用整数微单位，1 货币单位等于 1,000,000 micros。
- `AI_STORY_LIVE_LIMIT_CNY_MICROS` 或 `AI_STORY_LIVE_LIMIT_USD_MICROS` 提供本机上限，通过已有 `/api/text/projects/{project_id}/budgets` 建立同币种、同授权号的项目真实额度。固定规格的同币种预算也构成上限。预留和核算与文本共用项目预算和全局额度。调用前再次检查授权和额度；项目、价格或配置不满足条件时拦截。
- 发送前取消会释放预留。发送意图先落库，超时、服务拒绝或 Worker 失联均保留占用等待账单。有效收据和文件可在恢复后复用。相同请求有未结账任务时拦截重复发送。费用由人工提供凭证，允许按供应商证据登记 0；超出已核验上限会冻结后续真实调用。关闭图片开关后重启 API 与 Worker 即可禁发，已有账目仍可查证结算。

API 请求与响应契约使用 `httpx.MockTransport` 与本机样本验证。真实供应商可达性、返回图片质量及实付账单待授权后验证。动态视频、Codex 创作执行和自动视觉质检仍在后续阶段。

## 实际验收

- 后端全量 **174 项通过，0 失败，0 跳过**，用时 292.99 秒。最终图片专项 4 项通过，覆盖项目隔离、预算闸门、未知结果占用、停止重发、人工账单和 Worker 收据恢复。Vue 类型检查、Vite 生产构建和 Alembic 模型比对通过。保留一条现有的 Starlette/httpx 弃用提示。 [后端 JUnit](v3-13-backend.xml) · [图片专项 JUnit](v3-13-image-tests.xml)
- Chrome 实测 1024×1024 模拟 PNG 的解码和哈希、固定参考图并排查看、内容检查项门禁、人工通过、采纳入库、浏览器刷新、由生产队列直达同一候选，以及 390 像素宽布局。向导回归核对 12 个工作区和六阶段 24 步。 [图片截图](v3-13-image-workspace.png) · [图片浏览器记录](v3-13-image-browser.json) · [工作流导航](v3-13-navigation.json)
- 批准镜头保留固定规格 v2 和合同哈希，混用规格被拒绝。原链路继续完成 FFmpeg 720×720 候选、成片质检和授权 ZIP，ZIP 哈希通过校验。 [固定镜头与交付复验](v3-13-spec-browser.json)
- 独立备份恢复核对 7 个项目、13 项素材和 120 个文件，素材 Range 请求返回 206。本机保持 `0018`，新版图片页面与接口返回 200，Worker 在线，真实图片发送 0 次，真实额度 0。 [备份恢复](v3-13-recovery.json) · [本机状态](v3-13-readiness.json)

## 源码

- `backend/app/image_adapter.py` 实现离线图和 OpenAI Images 协议，`image_budget.py` 将图片预留与结算写入现有 P5 账本，`image_candidates.py` 负责固定输入、候选、审核与入库。
- `frontend/src/components/production/ImageCandidates.vue` 提供工作台。模型设置页、制作向导、生产队列与运行诊断显示图片入口或任务状态。

## 复验与回滚

```powershell
npm.cmd --prefix frontend run build
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --junitxml data/tmp/v3-image-backend.xml
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-image --browser-evidence data/tmp/v3-image-qa
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-spec --browser-evidence data/tmp/v3-image-spec
& ./.venv/Scripts/python.exe scripts/p6_recovery_check.py --stage image-candidates
```

回滚前先关闭真实图片开关，等待图片任务结束，并备份数据库和媒体。若有发送后尚未结算的任务，先保存供应商账单和调用编号，完成结算后再回退。停止本机服务，回退本次代码提交，重新构建并执行 `scripts/start.ps1 -Production`。沿用数据库 `0018`，保留已入库图片、任务和财务记录。必要时在独立数据库和目录恢复快照验证，确认后再切换配置。
