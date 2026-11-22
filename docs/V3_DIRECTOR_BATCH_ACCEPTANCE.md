# V3 总导演整剧生产与分集返工

2026-11-22 基于 `e057eb0` 增量开发。总导演从已批准的故事圣经读取分集，按集固定时间轴版本，并保存审批前的执行清单。旧批次可作为返工基线，每集显示重新渲染、复用成片与质检，或复用成片重新质检。准备计划不会入队。批准时重新核对 Guardian 规则、素材和可复用成片。审批时间、生产批次及分集任务在同一事务中提交。结果由现有 Worker 和生产接口提供。

## 验收

- Chrome 使用 FFmpeg 制作的真实样片，从总导演批准两集渲染与质检。刷新页面后可读取实际批次。随后只替换第二集，验证第一集复用原成片，第二集使用新的渲染任务，且两集通过质检。无授权时交付被拒绝，补齐授权后下载实际 ZIP。 [待审计划](director-batch-draft.png) · [第二集返工结果](director-batch-rework.png) · [HTTP 验收记录](director-batches-browser.json)
- 新增后端用例检查缺集拒绝、批准前无任务、并发批准幂等、产物损坏后拒执行旧计划、按集复用，以及只复检时沿用旧渲染。真实模型预算与支出均为 0 元。
- 后端全量 141 项通过，0 失败、0 跳过，用时 281.88 秒。只复检专项补充执行后，总导演 3 项通过。保留一条 Starlette/httpx 上游弃用提示。Vue 类型检查和 Vite 生产构建通过。原有 Guardian Chrome 流程也通过，两集十镜头产物、四个拒绝样本、九个复用镜头和 ZIP 均有记录。
- 独立库和目录恢复核对 7 个项目、13 项素材、120 个文件和 HTTP Range 206。演练完成 `0014 → 0015 → 0014 → 0015` 后，本机升级到 `0015`。Worker 在线，7 个现有项目均可读取批次选项，当前没有已批准的制作计划。批次生产使用隔离验收项目。 [迁移与恢复](director-batches-recovery.json) · [本机就绪](director-batches-readiness.json)

## 改动与复验

- 后端使用 `backend/app/director.py`、`production.py`、`models.py`、`main.py` 与迁移 `backend/migrations/versions/0015_director_batches.py`。
- 前端使用 `frontend/src/pages/DirectorPage.vue` 与 `frontend/src/components/production/DirectorBatchFields.vue`。
- 自动化包括 `backend/tests/test_director.py`、迁移版本断言，及 `scripts/browser-v3-director.mjs`、`browser-p14.mjs`、`p6_recovery_check.py`。

从工程根目录运行，测试使用隔离 PostgreSQL 与临时文件目录。

```powershell
npm.cmd --prefix frontend run build
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --junitxml data/tmp/director-batches-backend.xml
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-director --browser-evidence data/tmp/director-batches-qa
# 本机尚未启动，且已完成 0015 迁移时使用
& ./scripts/start.ps1 -Production
```

## 范围和回滚

制作说明随计划保存，由用户选择时间轴并审批。剧情改编、视觉语义质检和镜头级定向返工仍需各自的执行与审核流程。本轮返工粒度为分集。

回滚前等待队列空闲，停止本项目并备份当前库与生产文件。若尚未创建批次计划，可在当前源码的 `backend` 目录运行 `..\.venv\Scripts\alembic downgrade 0014`，再回退提交、构建并启动。已有批次计划时迁移拒绝移除批次关联。可保留当前库和文件，在独立库和目录恢复升级前的 `0014` 快照，使用 `e057eb0` 验证并切换，保留新版本全部记录与成片。
