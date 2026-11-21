# V3 第十批 · 整剧质检与增量复检

基于 `974ae37` 增量开发。整剧生产继续使用固定时间轴、PostgreSQL 和现有 Worker。模型治理沿用 P5 提交 `8b8a290`。P5 `0006` 备份文件的 SHA-256 与已归档的恢复记录一致。 [P5 恢复记录](p5-backup-migration-acceptance.json)

## 使用方法

1. 在「批量生产」打开已有批次。桌面上分集报告和成片监看并排显示，窄屏依次展示。可以筛选待复核或需返工的分集，从带时间的发现跳到成片或固定时间轴。
2. 选择「使用当前规则复检」。按需调整黑场、冻结、静音、整段响度和真峰值阈值。确认后创建独立复检批次。时间轴一致、成片和已发布字幕哈希一致的分集复用原 MP4，损坏产物会生成新渲染任务。
3. 告警需要填写人工复核意见。技术硬门槛失败需返工。已结束批次可下载 JSON 质检报告。最终交付按原授权流程办理，打包时会再次核对经质检的字幕。

## 判定规则

- FFmpeg 解码同一次扫描测量整段 EBU R128 响度和真峰值。可选阈值产生人工复核告警。无音轨或有效测量不足时保留空值。FFprobe 核对成片分辨率、编码、帧率和帧数。
- 质检读取实际输出的 SRT，检查 UTF-8 格式、时段、重叠、时间轴边界和发布哈希。旧批次临时 SRT 有文件时可以复检，并记录本次观察到的哈希。技术报告保留 `ffmpeg-technical-v2` 与固定成片哈希。
- 停止复检仅停止该批次任务。Worker 租约过期后可重领 QC 任务，保留中断记录、原渲染任务和可读取的 FFmpeg 执行日志。质检与成片文件没有新增数据库列。

## 实测结果

- 隔离 PostgreSQL 从空库迁移到 `0013`，`alembic check` 通过。后端 137 项通过，0 失败，0 跳过，用时 207.84 秒。质检恢复专项另行通过，验证 Worker 在解码阶段中断后重领，第 1 次尝试标记中断，第 2 次读取原成片成功，原渲染仍为第 1 次尝试。任务详情可读取第二次尝试的 FFmpeg 响度摘要。保留 Starlette/httpx 的上游弃用提示。 [全量 JUnit](v3-10-backend-tests.xml) · [恢复专项 JUnit](v3-10-qc-recovery.xml)
- Vue/TypeScript 类型检查与 Vite 生产构建通过。14 条已安装 Chrome 流程通过。浏览器核对成片监看和报告并排、JSON 下载、成片哈希一致、新复检使用独立任务及人工告警复核。自制样本测得 −21.7 LUFS 和 −20.7 dBTP，设置 −12 LUFS 下限后产生告警。 [Chrome 记录](v3-10-quality-browser.json) · [审片截图](v3-10-quality-review.png)
- 另一次真实 HTTP 批量生产用一个 Worker 渲染 6 集自产测试视频，共 180 秒，规格为 1280 × 720、24 fps。首轮渲染和质检 52.28 秒，复检 7.329 秒。6 个原渲染任务全部复用，6 份报告全部重算，每集测得音频指标并核对 2 条字幕。下载一集后复算 SHA-256。 [负载记录](v3-10-production-load.json)
- 复用上批完整备份，在独立 PostgreSQL 和文件目录完成恢复。核对 7 个项目、13 项素材及 120 个文件，恢复 API 的媒体 Range 请求返回 206。新版生产页已通过回环 HTTP 验证，1 个 Worker 在线。真实付费请求和支出均为 0。 [独立恢复记录](v3-10-recovery.json) · [本机就绪记录](v3-10-readiness.json)

## 修改文件

- 后端 `backend/app/quality.py`、`production.py`、`main.py`、`delivery.py`、`render.py`，以及 `backend/tests/test_production.py`、`test_delivery.py`。
- 前端 `frontend/src/ProductionStudio.vue`、`frontend/src/pages/ProductionPage.vue`。
- 验收 `scripts/browser-p11.mjs`、`scripts/browser-v3-production-load.mjs`、`scripts/isolated_regression.py`，以及 README、变更记录、验收索引和能力矩阵。

## 启动与复验

```powershell
Push-Location frontend
try {
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
} finally { Pop-Location }
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --v3-browsers --junitxml data/tmp/v3-10-backend.xml --browser-evidence data/tmp/v3-10
# PostgreSQL 就绪且工作台尚未运行时启动
& ./scripts/start.ps1 -Production
```

## 回滚

队列空闲且已跟踪工作区干净时，通过反向提交撤回本批。数据库继续使用 `0013`。工作台仍可读取本批生成的成片和已保存的历史记录。

```powershell
$release = git log -1 --format=%H --grep='^Improve series quality review and recheck published renders$'
if (-not $release -or (git status --porcelain --untracked-files=no)) { throw 'Confirm the release commit and a clean tracked worktree.' }
& ./scripts/stop.ps1
git revert --no-edit $release
if ($LASTEXITCODE -ne 0) { throw 'Resolve the revert before restarting.' }
Push-Location frontend
try {
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
} finally { Pop-Location }
& ./scripts/start.ps1 -Production
```

## 验收范围

- 字幕检查覆盖随附 SRT 的文件完整性和时序。烧录文字的像素检查、字幕与对白的语义同步，以及角色、剧情、画面一致性仍待验证。
- 复用前要读取原产物的哈希。大体积长剧的提交延迟、资源峰值、复杂多轨及商业高负载仍待专项测量。
- 真实付费预算为 0。模型效果和实际收费的验收仍需独立授权。
