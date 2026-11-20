# V3 第五批软字幕校对与烧录验收

基线为 `66e0371`。范围为已提取的软字幕、校对版 SRT、素材及剪辑交接。

## 操作与数据

1. 在“智能解析”选择授权视频，执行“软字幕提取”，打开“字幕”并选择轨道。
2. 选择字幕行，播放器跳到对应源时间。可以改文案和起止毫秒、定位新起点、移除本条或恢复原字幕。保存时校验时间先后、轨内重叠、已知源时长、文本结构及 2 MiB 文件限制。
3. “保存字幕素材”生成 UTF-8 SRT 并登记不可变版本。相同轨道的相同成品复用已有版本。版本保存源素材与解析任务、提取 SRT 和派生 SRT 的哈希及授权来源。视频原件和提取产物均保留。
4. 保存后可下载 SRT，或选择“带入剪辑”。剪辑页预选源视频和对应字幕，用户确认后由现有 Worker 按固定素材哈希渲染。SRT 也可在多轨时间轴的字幕轨选择。

## 实测

- 隔离 PostgreSQL 从空库迁移到 `0013`，`alembic check` 通过。后端 125 项通过，0 失败，0 跳过，耗时 182.54 秒，保留 1 条 Starlette/httpx 上游弃用提示。新增用例覆盖项目和素材隔离、排队时拒绝保存、非整数毫秒、重叠、越界、空行、删除全部、重复提交、独立版本、原件完整性和文件损坏。 [后端 JUnit](v3-05-backend-tests.xml)
- 生产构建通过 Vue/TypeScript 和 Vite，12 条 Chrome 流程通过。字幕专项使用自制的 2 秒视频和 52 条软字幕。纠正重叠后保存两个版本，重复保存复用 v1，刷新后可查看并下载两个版本。开启剪辑后核对预选文件、Worker 固定的字幕哈希和输出文件。ffprobe 实测 H.264 成片时长 2 秒。取字幕区三帧，时间范围前、中、后的亮像素为 0、422、0，验证字幕只在修订时间段烧录。原视频 SHA-256 复验一致。 [浏览器证据](v3-05-subtitle-browser.json) · [实际截图](v3-05-subtitle-review.png)
- 本机停写后完成备份和独立恢复，核对 7 个项目、13 项素材和 120 个文件，恢复后的素材 Range 读取返回 206。生产构建已在 127.0.0.1:15173 运行，前端、解析路由、新 API 和 1 个 Worker 就绪。真实调用仍关闭，CNY 和 USD 预算均为 0。 [恢复证据](v3-05-recovery.json) · [本机就绪](v3-05-readiness.json)

## 修改文件

- 后端 `backend/app/analysis_engine.py`、`analysis_routes.py`、`subtitle_revision.py` 及 `backend/tests/test_media_analysis.py`。复用素材表及持久化队列，迁移保持 `0013`。
- 前端 `frontend/src/MediaAnalysis.vue`、`SubtitleDraft.vue`、`VideoEditor.vue` 及 `pages/AnalysisPage.vue`、`VideoPage.vue`。
- 验收脚本 `scripts/browser-p6.mjs`，版本入口、能力矩阵、截图及本报告。

## 复验与回滚

```powershell
Push-Location frontend
npm.cmd run build
Pop-Location
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --v3-browsers --junitxml data/tmp/v3-05-backend.xml --browser-evidence data/tmp/v3-05
# 在本机 PostgreSQL 已就绪且服务已停止时启动
& ./scripts/start.ps1 -Production
```

要回滚，确认本机队列空闲、Git 所有已跟踪文件没有其他改动，再执行：

```powershell
$release = git log -1 --format=%H --grep='^Review extracted subtitles and render fixed revisions$'
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

保存的 SRT 继续以通用素材可用。校对面板以同一提取轨道为底稿，切换轨道或离开页面会丢失未保存草稿。媒体时长校验依赖已有探测值，旧记录缺少时长时保留时间格式、轨内重叠和 24 小时上限检查。自动语音转写、硬字幕持续时间识别和软字幕视频输出仍待开发。外部调用和实际模型费用为 0。
