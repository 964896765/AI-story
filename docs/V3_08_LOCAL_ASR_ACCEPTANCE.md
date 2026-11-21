# V3 第八批本机语音转写

基于 `c931cfb` 增量开发。Windows 桌面语音识别通过本机 `System.Speech` 听写引擎运行，沿用现有 Worker、解析缓存、项目权限及字幕素材版本。

## 操作与数据

1. 在“项目与素材 → 智能解析”选择授权素材。多音轨素材先运行“流清单”，再选择“本机语音转写”的源流、语言及起止时间。
2. Worker 从指定轨道提取 16 kHz 单声道 PCM，保留源时间偏移。Windows 识别结果包含分段起止、文字和引擎置信值。可试听实际送入识别器的音频。
3. 打开“转写”，点击字幕行定位音频和源时间。定位链接可以重开同一转写任务、试听文件与位置。静音扫描保留试听文件和实际空结果。
4. 可逐条校对、保存独立 SRT 版本、下载并带入剪辑。成片音轨按剪辑配置。保存的 SRT 仍可在对应轨道从历史版本继续编辑，原媒体、原识别字幕和审核版分别保留。

## 实测

- 13 条 Chrome 生产构建流程通过，使用本机 Windows 自带识别器的专项流程也已复验通过。16 秒双音轨样片的第一条音轨为静音，选择第二条音轨的 2–15 秒后真实识别出 3 条。第一条起于源时间 2.610 秒，试听文件同一位置为 0.610 秒。打开定位链接恢复同一试听和位置。原片哈希保持一致，校对 SRT 后实际生成成片，成片范围请求为 206。 [浏览器记录](v3-08-asr-browser.json) · [校对截图](v3-08-asr-review.png)
- 本机转写专项通过 2 项。验证了非零起点、静音空结果、错误流类型、未安装语言、SRT 校对与来源哈希。 [专项 JUnit](v3-08-asr-tests.xml)
- 后端隔离 PostgreSQL 从空库迁移到 `0013`，Alembic 比对通过。最终全量 130 项通过，0 失败、0 跳过，耗时 224.95 秒，保留 1 条 Starlette/httpx 弃用提示。首轮有一条旧测试断言语音转写一定处于待接入状态。更新为核对已安装语言检测后重跑通过。 [后端 JUnit](v3-08-backend-tests.xml)
- Vue/TypeScript 与 Vite 生产构建通过。本机停写后独立恢复核对 7 个项目、13 项素材、120 个文件，素材 Range 请求返回 206。重启后前端、Worker、简体中文识别器和转写接口均就绪。真实付费预算为 0。 [独立恢复](v3-08-recovery.json) · [本机就绪](v3-08-readiness.json)

## 文件

- 后端 `backend/app/analysis_engine.py`、`analysis_review.py`、`analysis_routes.py`、`analysis_schemas.py`、`analysis_service.py`、`perception.py`、`perception_asr.py` 和 `subtitle_revision.py`。
- 前端 `frontend/src/MediaAnalysis.vue`、`analysisApi.ts`。
- 本机适配与验收 `scripts/recognize_speech.ps1`、`scripts/browser-v3-asr.mjs`、`scripts/isolated_regression.py`、`backend/tests/test_local_asr.py`、`test_media_analysis.py`。数据库继续使用 `0013`。

## 复验与回滚

```powershell
Push-Location frontend
npm.cmd run build
Pop-Location
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --v3-browsers --junitxml data/tmp/v3-08-backend.xml --browser-evidence data/tmp/v3-08
```

回滚前确认队列空闲、已跟踪文件没有其他改动、当前没有待处理的转写任务。已保存的 SRT 可作为通用素材继续使用。

```powershell
$release = git log -1 --format=%H --grep='^Transcribe timed audio with Windows offline speech$'
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

- 使用 Windows 自带的桌面识别器，当前实测简体中文。更换系统识别语言后需重启 API 和 Worker。每次最多 180 秒，长音频可分段处理，各段分别保存。分段时间和置信值来自本机引擎，仍需人工校对。
- 实测使用自编文本与 Windows 自带合成音色。嘈杂环境、方言、重叠对白和真实多人录音仍待独立验收。说话人分段和音源分离仍待开发。
- 项目只随源码分发调用脚本。识别器及音色由本机 Windows 提供。真实外部调用与付费预算为 0。
