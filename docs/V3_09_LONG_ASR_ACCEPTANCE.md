# V3 第九批长音频转写

基于 `f413e67` 增量开发。沿用 Windows 本机识别器、同一媒体解析任务及 SRT 版本链。

## 操作与处理

1. 在“智能解析 → 本机语音转写”选择素材、音轨、语言及最长 30 分钟的源时间区间。超过 180 秒的音频自动分段。
2. Worker 从连续的 16 kHz 音轨按每 170 秒切分核心区间，相邻段各带 5 秒前后上下文，单次识别输入不超过 180 秒。每段保留源时间。合并优先选离名义分界最近、两段识别结果均无字幕的空档。没有合适空档时按分界择取，处理时间重叠并标记该接缝供复核。
3. 已完成的分段结果写入任务专用检查点，以源哈希、转写配置、引擎、分段算法及窗口匹配，并校验内容 SHA-256。Worker 重新领取原任务时重新解码试听音轨，续用有效转写片段。发布仍在所有分段完成并验证后进行。
4. 打开“转写分段与接缝”可查看各段时段、条数及接缝，使用连续音轨试听定位。最终校对和下载均以同一份源时间 SRT 为准。

## 验收范围

- 长音频专项 5 项通过。包含 193 秒真实语音识别、重复对白在时间上保持独立、跨界对白合并、不同分段结果冲突提示、检查点校验。模拟 Worker 在首段后中断并让租约过期。重新领取时第 2 次执行只识别 165–193 秒，首段检查点被复用。 [专项 JUnit](v3-09-asr-tests.xml)
- 30 分钟配置上限通过真实引擎检查。用 Windows 本机配音生成自编对白，放在 0、167.5 和 1790 秒，其余时间留静音。直接运行同一分析引擎，完成 11 段与完整试听 WAV，耗时 49.125 秒，保留距末尾约 8 秒的对白。 [满区间实测](v3-09-max-range.json)
- Vue/TypeScript 与 Vite 生产构建通过，14 条 Chrome 流程通过。193 秒视频的识别区间为 0–175 秒与 165–193 秒，合并点为 170.450 秒。Chrome 跳转到接缝和 182.080 秒的对白，校正实际识别出的错词后生成统一 SRT，并核对文件哈希。 [浏览器记录](v3-09-long-asr-browser.json) · [实际截图](v3-09-long-asr.png)
- 后端隔离 PostgreSQL 从空库迁移到 `0013`，Alembic 比对通过。全量 133 项通过，0 失败、0 跳过，耗时 263.79 秒，保留 1 条 Starlette/httpx 上游弃用提示。 [后端 JUnit](v3-09-backend-tests.xml)
- 停写后独立恢复核对 7 个项目、13 项素材和 120 个文件。重启后新版前端、Worker 和 1800 秒转写配置就绪，真实付费预算为 0。 [恢复记录](v3-09-recovery.json) · [本机就绪](v3-09-readiness.json)

## 文件

- 后端 `backend/app/asr_chunks.py`、`perception_asr.py`、`analysis_engine.py` 和 `analysis_service.py`。数据库保持 `0013`。
- 前端 `frontend/src/MediaAnalysis.vue`、`analysisApi.ts`。
- 验收 `backend/tests/test_local_asr.py`、`scripts/browser-v3-long-asr.mjs` 与 `scripts/isolated_regression.py`。

## 复验与回滚

```powershell
Push-Location frontend
npm.cmd run build
Pop-Location
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --v3-browsers --junitxml data/tmp/v3-09-backend.xml --browser-evidence data/tmp/v3-09
```

回滚前确认队列空闲、已跟踪文件没有其他改动。已保存的 SRT 可以继续作为通用素材使用。

```powershell
$release = git log -1 --format=%H --grep='^Resume and merge long offline speech recognition$'
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

- 193 秒样片覆盖 Worker、Chrome 与 SRT 校对全流程。30 分钟上限实测使用有长静音的自制 WAV。密集对白的吞吐、嘈杂音频、多人重叠对白及说话人分段待单独验证。
- 接缝依据两段识别结果推断。连续对白或识别歧义可能需要回听修正。任务恢复时会重新解码试听音轨，已验证的识别片段可跳过。
- 仍由 Windows 本机运行，付费请求与实际费用为 0。
