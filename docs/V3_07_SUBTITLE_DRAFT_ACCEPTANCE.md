# V3 第七批字幕版本与草稿

基于 `532a316` 增量开发。适用于软字幕提取和硬字幕识别后的校对。

## 操作与数据

1. 在“智能解析”的字幕结果中展开已保存字幕，选择需要的版本并点击“继续编辑”。工作区显示当前底稿。后端按项目、素材、解析任务和轨道校验版本归属，核对 SRT 的文件大小和 SHA-256，再返回底稿字幕。
2. 修改文案、起止时间或移除条目，播放时可切换“预览校对稿”和“预览原字幕”。校对稿按修改后的时间显示，移除或时间无效的条目在预览中隐藏。
3. 草稿按项目、素材、解析任务、轨道保存于当前浏览器。刷新或重新进入对应轨道可恢复历史底稿和各条修改。切换底稿前可保存或放弃草稿。保存成功并重新读回版本后，清理当前草稿。
4. 另存的版本记录底稿 ID 和哈希。相同 SRT 内容复用已有素材。删除字幕行或调整时间后，历史字幕和使用它的成片仍可按原哈希查验。

## 实测

- 隔离 PostgreSQL 从空库迁移至 `0013`，Alembic 比对通过。后端 128 项通过，0 失败、0 跳过，耗时 197.64 秒，保留 1 条 Starlette/httpx 弃用提示。用真实解析素材验证读取历史版、底稿归属、编辑索引、损坏文件拒绝和按内容幂等。 [后端 JUnit](v3-07-backend-tests.xml)
- Vue/TypeScript 和 Vite 生产构建通过。12 条 Chrome 流程通过。用包含 52 条软字幕的自制样片恢复 v1 的未保存字幕文字、时间和删行，复核原字幕与校对稿切换，再另存 51 条的 v3。使用 v2 的既有成片及其字幕文件复验 SHA-256 一致。首轮 OCR 回归脚本在能力加载前触发按钮，补上等待条件后全量重跑通过。 [浏览器证据](v3-07-subtitle-draft-browser.json) · [恢复草稿截图](v3-07-restored-subtitle-draft.png)
- 本机停写后在独立环境恢复 7 个项目、13 项素材和 120 个文件，素材 Range 请求返回 206。重启后验证新构建、字幕详情 API、1 个 Worker 和 0 元付费预算。 [恢复记录](v3-07-recovery.json) · [本机就绪](v3-07-readiness.json)

## 实现文件

- 后端 `backend/app/analysis_engine.py`、`analysis_routes.py`、`subtitle_revision.py`、`backend/tests/test_media_analysis.py`。
- 前端 `frontend/src/MediaAnalysis.vue`、`SubtitleDraft.vue`、`analysisApi.ts`。
- 浏览器流程 `scripts/browser-p6.mjs` 与 `scripts/browser-p6-ocr.mjs`。数据库使用现有素材和解析任务表，Alembic 保持 `0013`。

## 复验

```powershell
Push-Location frontend
npm.cmd run build
Pop-Location
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --v3-browsers --junitxml data/tmp/v3-07-backend.xml --browser-evidence data/tmp/v3-07
```

## 回滚

确认队列空闲、已跟踪文件没有其他改动后执行。已保存的 SRT 作为素材继续可用。

```powershell
$release = git log -1 --format=%H --grep='^Resume subtitle revisions and restore local drafts$'
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

- 草稿存在同一个浏览器配置和本机访问地址下，清理网站数据会移除草稿。存储满或被禁用时面板会提示，仍可手动保存正式版本。
- 校对面板显示当前轨道最近 20 个已保存版本。
- 硬字幕原始采样图在原字幕底稿中可定位。历史 SRT 经删行或改时后的每行没有单独的采样图索引，原始视频和解析记录可用于复核。
- 付费模型保持关闭，实际调用和金额为 0。
