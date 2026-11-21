# V3 第六批硬字幕时序识别

基于 `f999c4f` 增量开发，使用现有项目、Worker、Windows OCR 与 SRT 校对版本。数据库沿用 `0013`。

## 操作与数据

1. 在“项目与素材 → 智能解析”选择视频和“硬字幕时序识别”。选择已安装的 OCR 语言、画面底部 40% 或完整画面、采样间隔及起止时间。
2. Worker 按真实视频帧时间戳采样。相邻帧中文字一致时合并时段。空白帧、文字变化或较大时间戳间隔会切段。结果标记为“需要校对的 OCR 估算时序”。
3. 打开“硬字幕”结果，点击条目回到源时间并对照首个识别画面。修改文字、毫秒起止或删除误识别条目后，可保存、下载或选用固定 SRT 版本。
4. “带入剪辑”预选字幕版本，便于选择无旧字幕的底片。原视频、采样证据、未修改识别结果和人工修订版各自保留。SRT 记录源素材哈希、OCR 任务、扫描参数及采样证据指纹。

## 实测

- 隔离 PostgreSQL 从空库迁移到 `0013`，Alembic 比对无差异。后端 128 项通过，0 失败、0 跳过，耗时 261.23 秒，保留 1 条上游 Starlette/httpx 弃用提示。专项 3 项包含空白帧和时间戳间隙分段、参数校验、真实 FFmpeg 与简体中文 OCR。 [后端 JUnit](v3-06-backend-tests.xml)
- `vue-tsc` 与 Vite 生产构建通过。12 条 Chrome 流程通过。3 秒自制样片在 0.25–2.75 秒扫描 10 帧，识别到 0.50–1.25 秒和 1.75–2.50 秒两段，与样片设定一致。样片上方水印被底部扫描排除。浏览器完成校对、SRT 下载、固定版本带入剪辑和 Worker 渲染。取成片下方五帧，暗像素计数为 0、3100、0、1658、0。源视频哈希复验一致。 [浏览器证据](v3-06-hard-subtitles.json) · [校对截图](v3-06-hard-subtitles.png)
- 本机停写后在独立环境恢复 7 个项目、13 项素材及 120 个文件，复验素材范围读取 206。重启后本机工作台、1 个 Worker、简体中文 OCR 及硬字幕 API 均就绪。真实调用关闭。 [恢复记录](v3-06-recovery.json) · [本机就绪](v3-06-readiness.json)

## 文件

- 后端 `backend/app/analysis_{engine,review,routes,schemas,service}.py`、`perception_ocr.py` 和 `subtitle_revision.py`。
- 前端 `frontend/src/MediaAnalysis.vue`、`SubtitleDraft.vue` 和 `analysisApi.ts`。
- 验收 `backend/tests/test_ocr_subtitles.py` 与 `scripts/browser-p6-ocr.mjs`，以及 README、能力矩阵和本报告。

## 复验与回滚

```powershell
Push-Location frontend
npm.cmd run build
Pop-Location
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --v3-browsers --junitxml data/tmp/v3-06-backend.xml --browser-evidence data/tmp/v3-06
```

回滚前确认本机队列空闲、Git 已跟踪文件没有其他改动。已保存的 SRT 可作为通用素材使用，数据库继续使用 `0013`。

```powershell
$release = git log -1 --format=%H --grep='^Recognize hard subtitle intervals and review SRT$'
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

## 已知限制

- 每次最多 120 帧，采样间隔 0.25–2 秒。低对比、特效、采样间隙内短暂字幕和位置相似的画面文字仍需人工核对。长片按区间扫描，各区间分别保存。
- 起止时间是基于采样的估算。当前使用文字一致性合并，OCR 误读可能切成多条。其他语言以系统实际安装的语言为准。
- 对外模型请求关闭，真实付费请求和实际费用为 0。
