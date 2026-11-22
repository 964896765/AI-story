# V3 AI 总导演本机执行验收

2026-11-22 基于 `f7d8152` 增量交付。

- 固定时间轴计划引用不可变时间轴版本及素材快照。创建计划只保存待审核记录。批准时复核原有 Guardian 和输入检查，再原子保存批准时间与任务关联。并发执行同一计划会返回同一任务。
- 交付计划核对整剧技术质检、人工复核、平台和地域授权。批准时比对授权修订及质检文件指纹，Worker 打包和下载继续使用原交付校验。
- PRISM 三栏显示计划历史、Worker 阶段、进度、耗时和错误。渲染成功可预览或下载。交付成功可下载 ZIP。取消、重试与详细日志可在生产队列操作。真实外部模型支出为 0 元。

## 验收结果

- 隔离 PostgreSQL 从空库升到 `0014`，`alembic check` 无差异。全量后端 140 项通过，0 失败、0 跳过，用时 168.31 秒。保留一条 Starlette/httpx 上游弃用提示。专项覆盖跨项目拒绝、素材版本变化、并发审批防重复、无授权阻断、授权更新后旧计划拒绝、实际渲染 Range 206 和交付 ZIP 哈希。
- Vue 类型检查和 Vite 生产构建通过。Chrome 使用真实 FFmpeg 视频通过总导演两条路径，包括待审计划刷新恢复、批准、成片解码、缺少授权拦截、补齐授权和 ZIP 下载。PRISM 总览、12 个导航入口和人工 Guardian 交接流程一并回归通过。 [渲染截图](director-render.png) · [交付截图](director-delivery.png) · [真实 HTTP 验收](director-browser.json)
- 已将本机 `0013` 数据库和关联生产文件恢复至独立库和目录，核对 7 个项目、13 项素材、120 个文件及素材 HTTP Range 206。隔离库完成 `0013 → 0014 → 0013 → 0014`，随后本机升级至 `0014`。本机 7 个项目的总导演历史接口可读，Worker 在线，真实模型授权关闭且预算为 0。 [恢复记录](director-recovery.json) · [本机就绪](director-readiness.json)

## 修改文件

- 后端及迁移为 `backend/app/director.py`、`main.py`、`models.py`、`timeline.py`、`delivery.py` 和 `backend/migrations/versions/0014_director_plans.py`。
- 前端为 `frontend/src/pages/DirectorPage.vue`、`frontend/src/layouts/WorkbenchLayout.vue`。
- 验证为 `backend/tests/test_director.py`、`test_render_postgres.py`、`test_system_release.py`、`test_text_governance.py`，以及 `scripts/browser-v3-director.mjs`、`browser-p14.mjs`、`isolated_regression.py`、`p6_recovery_check.py`。

## 启动与复验

从工程根目录运行。全量后端与专项浏览器使用独立 PostgreSQL 库，浏览器验收另外使用临时文件目录。

```powershell
npm.cmd --prefix frontend run build
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --junitxml data/tmp/director-backend.xml
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-director --browser-evidence data/tmp/director-qa
# 本机尚未启动，且已完成迁移时使用
& ./scripts/start.ps1 -Production
```

## 待开发

剧情改编和镜头返工继续由人工交接。模型驱动的导演规划、整剧批次编排、视觉语义质检与定向返工仍待实现或验证。总导演为本机工作台，计划批准时间可追溯，尚无多用户审批身份。

## 回滚

队列空闲后运行 `scripts/stop.ps1`，备份当前 `0014` 数据库和生产文件。若尚无总导演计划，使用当前源码在 `backend` 执行 `..\.venv\Scripts\alembic downgrade 0013`，再回退本次 Git 提交、重新构建并启动。迁移会拒绝删除含计划的表。已有计划时，可保留当前数据库和文件，在独立 PostgreSQL 库和目录恢复升级前的快照，用 `f7d8152` 构建，在独立配置下核验后切换。升级后创建的计划及产物保存在原库和原目录。
