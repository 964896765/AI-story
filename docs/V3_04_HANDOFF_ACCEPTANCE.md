# V3 第四批生产与交付验收

基于 `6f0dd19` 增量开发。V2 Windows 本机版已经完成发布验收。V3 目前交付了全局工作台、智能解析、主要制作页面改版和本批生产交付流程。 [V2 发布](P14_ACCEPTANCE.md) · [V3 工作台](V3_01_ACCEPTANCE.md) · [智能解析](V3_02_ANALYSIS_ACCEPTANCE.md) · [制作页面](V3_03_WORKBENCH_ACCEPTANCE.md)

## 实际交付

|工作区|操作与数据来源|
|---|---|
|项目总览|根据最近批次、分集复核、返工和交付任务状态给出下一步。待处理分集可以直接打开，清单最多显示 8 集，批次页可看全部。无批次时可进入待审核改编稿。|
|批量生产与时间轴|筛选待复核与返工。通过批次和分集链接打开问题记录，点击质检发现可跳到成片起始时间，或进入关联的固定版时间轴片段。回到原批次时恢复分集焦点。局部返工表单打开后可替换相关分集。|
|资源与交付|通过项目限定接口打开固定批次。按平台和地域查询质检及授权阻塞项。可定位素材、追加授权版本和重新预检。预检只读，提交、Worker 打包及下载继续校验对应质检和授权。|
|发行与运营|成功的 ZIP 可带入人工发行表单，预选包及标题，按平台和地域显示可用渠道。打开表单后仍需人工保存发行草稿。|

## 实测

- 隔离 PostgreSQL 从空库迁移到 `0013`，`alembic check` 通过。后端 124 项通过，0 失败，0 跳过，耗时 147.45 秒。保留 1 条 Starlette/httpx 上游弃用提示。交付用例验证不入队的预检、项目隔离、参数校验、授权范围、过期和撤回、授权版本变化及实际 ZIP 哈希。 [后端 JUnit](v3-04-backend-tests.xml)
- `npm.cmd run build` 通过 `vue-tsc` 和 Vite 构建。已安装 Chrome 使用生产构建跑通 12 条流程。用自制样片实测 0–625 毫秒黑场定位、固定片段跳转、返工版本渲染和重新质检。缺少授权时预检拦截并保持队列为空，补权后下载 146,204 字节的真实 ZIP，重新计算 SHA-256 并与任务记录比对。固定批次刷新、手工发行预选和返回原批次均通过。 [浏览器记录](v3-04-browser.json) · [分集质检](v3-04-episode-qc.png) · [授权预检](v3-04-preflight.png) · [人工发行](v3-04-operations.png)
- 停写后备份本机数据库及关联存储，在独立 PostgreSQL 库和存储目录恢复 7 个项目、13 项素材和 120 个文件，核对文件 SHA-256 和素材 HTTP Range 206。数据库继续使用 `0013`。 [恢复记录](v3-04-recovery.json)
- 本机生产构建已在 127.0.0.1:15173 运行。健康检查、1 个在线 Worker、7 个现有项目总览和 3 项新增只读 API 就绪。真实付费模型关闭，预算为 0，本批实际付费请求 0 次。 [本机就绪记录](v3-04-readiness.json)

## 文件清单

- 后端 `backend/app/delivery.py`、`overview.py`、`production.py`，以及 `backend/tests/test_delivery.py`。
- 前端 `frontend/src/LibraryDelivery.vue`、`OperationsStudio.vue`、`ProductionStudio.vue`，`pages/{Library,Operations,Overview,Production,Timeline}Page.vue` 和 `types/workbench.ts`。
- 浏览器验收 `scripts/browser-p11.mjs`、`scripts/browser-p12.mjs`。文档 `README.md`、`docs/ACCEPTANCE.md`、本报告及同批证据。

## 本机启动、复验与回滚

```powershell
Push-Location frontend
npm.cmd run build
Pop-Location
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --v3-browsers --junitxml data/tmp/v3-04/backend-tests.xml --browser-evidence data/tmp/v3-04
# PostgreSQL 已就绪且本项目未运行时启动
& ./scripts/start.ps1 -Production
```

回滚前确认队列空闲，保留本机配置和存储，并先处理工作树中的其他源码改动。以下命令通过反向提交撤回本批。数据库继续使用 `0013`，恢复演练的副本留在本机备份目录。

```powershell
$release = git log -1 --format=%H --grep='^Connect batch review to rights-gated delivery$'
if (-not $release -or (git status --porcelain --untracked-files=no)) { throw 'Confirm the release commit and a clean tracked worktree.' }
& ./scripts/stop.ps1
git revert --no-edit $release
if ($LASTEXITCODE -ne 0) { throw 'Resolve the revert before restarting.' }
Push-Location frontend
try {
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
} finally {
    Pop-Location
}
& ./scripts/start.ps1 -Production
```

预检反映查询时的质检和授权状态，正式输出以提交、打包和下载时的重新校验结果为准。发行仍由人工操作。真实外部模型、实际供应商账单、ASR、说话人识别、音源分离、商业长剧负载及真实平台接入仍待开发或独立验收。 [能力矩阵](CAPABILITY_MATRIX.md)
