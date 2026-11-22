# V3 总导演模型规划

2026-11-22 基于 `17119ae` 增量交付。总导演模型规划当前开放离线模拟。真实模型调用保持关闭，实际外部支出为 0 元。

## 使用

1. 在项目的「文本模型与预算」启用模拟供应商，并配置独立模拟额度。
2. 在总导演保存固定时间轴渲染、整剧生产或授权交付计划。在「模型规划（离线模拟）」勾选一至四个待审批方案，填写目标并生成建议。模拟适配器按提交顺序推荐首个方案，用于验证流程。
3. 在建议记录中核对理由、复核事项和模拟核算。采纳后会打开对应的固定执行计划，操作员可单独批准执行。输入、授权及可复用产物在采纳和批准两个环节均重新核对。
4. 已发出的模拟调用、提示词版本、预算和审核记录保存到原有 PostgreSQL 模型账本。取消支持发送前释放。响应或用量不明时会保留占用并阻止重试，可确认本机模拟无实付后释放额度。

模型输入使用项目内已保存的固定方案摘要和操作员目标。响应只接受方案序号、理由和复核事项。越界序号、错误结构及未明确用量的结果无法进入审核。用户可继续使用原有手工执行计划与剧情改编入口。

## 验收

- 后端专用用例验证了未配置预算、真实供应商拒绝、跨项目隔离、并发幂等、选项范围、费用未知占用、取消释放和陈旧输入拒绝。用受控适配器选择第二个方案，核对采纳未创建制作任务。单独批准后使用 FFmpeg 实际合成，Range 请求返回 206。
- 最终全量后端 150 项通过，0 失败、0 跳过，用时 174.90 秒。隔离库 Alembic 模型比对通过，保留一条 Starlette/httpx 上游弃用提示。
- Chrome 走通固定方案、离线建议、刷新后恢复、人工采纳、单独批准与本机渲染。两集生产、分集返工与授权 ZIP 同步回归。 [规划界面](director-model-advice.png) · [浏览器记录](director-advice-browser.json)
- 原 P5 模拟剧情改编流程的 Chrome 回归通过，包括固定原稿、人工编辑、键盘审批和真实本地素材处理。Vue 类型检查及 Vite 生产构建通过。
- 上线前在独立库和文件目录恢复本机 `0015`，核对了 7 个项目、13 项素材、120 个文件及素材 HTTP Range 206。本机总导演返回 200，Worker 在线，七个项目的建议历史可读。验收配置在隔离库内，本机可用模拟供应商和有可用模拟额度的现有项目数量均为 0。 [恢复记录](director-advice-recovery.json) · [本机就绪](director-advice-readiness.json)

## 源码与复验

- 后端涉及 `backend/app/director.py`、`director_guidance.py`、`text_service.py`、`text_schemas.py`、`text_adapters.py`、`adaptation_policy.py`、`text_routes.py`、`overview.py`。
- 前端涉及 `frontend/src/pages/DirectorPage.vue`、`frontend/src/components/production/DirectorAdvice.vue`、`frontend/src/components/production/TaskList.vue`、`frontend/src/SystemStudio.vue`。
- 验收涉及 `backend/tests/test_director_advice.py`、`scripts/browser-v3-director.mjs`。本地数据库沿用 `0015`。

```powershell
npm.cmd --prefix frontend run build
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --junitxml data/tmp/director-advice-final-backend.xml
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-director --browser-evidence data/tmp/director-advice-final
# 本机尚未启动时使用
& ./scripts/start.ps1 -Production
```

## 待开发与回滚

真实模型规划和视觉语义识别仍待接入或验收。当前建议以手工准备的固定方案为输入。

回滚前等待队列空闲，处理完当前导演调用或取消排队项，保存当前数据库和文件。尚无导演建议记录时，运行 `scripts/stop.ps1`，反向提交本批、重新构建并运行 `scripts/start.ps1 -Production`。数据库使用 `0015`。已有建议记录时，旧版会将它们列入剧情改编历史。此时在独立库和目录恢复升级前快照并核验，再用 `17119ae` 构建和启动，当前数据库及生产文件保留用于后续恢复。
