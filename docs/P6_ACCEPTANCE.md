# P6 本地解析与证据审核

实施基线为 P5 提交 `8b8a290`。本轮接续工作区已有的 P6 解析引擎和媒体迁移，接通浏览器任务、结果预览、审核与创作版本引用。P6-A 本地解析按下列样本通过，P6-B 的人工审核、证据链和适配器契约通过。ASR、OCR、说话人分段、音源分离及多模态视觉理解尚待实际接入。

## 已交付

- 音视频分别可发起流清单、流复制分轨、转封装、MP4 代理、时间/间隔/关键帧抽帧、自动切镜、软字幕提取、波形与静音分析。流清单保留时间基、语言、色彩和旋转信息，已验证代理输出的实际画幅与音轨。VFR/CFR 界面展示取样状态。
- Worker 通过固定原件哈希、参数、引擎及工具版本建立签名。重复解析可复用哈希核验后的派生文件。步骤独立排队、取消、重试，提交批次按全部步骤做幂等校验。结果和产物仅在验证后开放 HTTP，并支持 Range 和下载。
- 人工审核可修订切点、整理字幕与镜头的时间重叠关系、标注时间证据、关联角色与场景候选。审核快照追加保存，采用期望版本限制并发覆盖。人工采纳后可引用已审核剧本、角色与场景固定版本。

## 证据

- 后端 104 项通过，0 项失败，0 项跳过，保留 1 条 Starlette/httpx 上游弃用提示。覆盖多音轨、真实 SRT、VFR、旋转、无音轨、损坏文件、原件 SHA-256、缓存损坏、取消重试和审核版本/来源隔离。 [后端测试](p6-backend-tests.xml)
- Vue/TypeScript 检查、Vite 生产构建、`pip check` 均通过。Chrome 在备用回环端口与独立服务/数据库/目录中完成八个操作，确认 4 条媒体流和对应派生分轨，代理时间元数据可读且 Range=206，两个视觉镜头的切点为 1 秒。已完成字幕跨镜头对齐、快照、键盘采纳和 P5 固定原稿接力，未捕获 JS 异常。首轮浏览器脚本在同一渲染周期连续点击复选框，只提交了 2 个步骤，修正为等待每次页面更新后复验通过。 [浏览器与 HTTP 证据](p6-browser-acceptance.json) · [解析页](p6-analysis.png) · [审核页](p6-review.png)
- 实际模型请求与费用均为 0。FFmpeg 使用自编字幕、自行生成色块和音调，音轨分拆按源文件的独立流执行。感知模型接口当前只返回可用性。
- 备份还原到独立数据库和独立目录，复核 7 个项目、13 条素材记录、115 个数据库关联文件哈希。独立恢复库通过 0006→0007→0006→0007 和模型差异检查。原工作台有序停机后完成 0007 迁移并重启。快照范围为数据库及数据库关联的素材、输出和任务文件。 [备份与迁移证据](p6-backup-migration-acceptance.json)

## 文件与迁移

- 后端新增 `analysis_engine.py`、`analysis_schemas.py`、`analysis_service.py`、`analysis_routes.py`、`analysis_review.py` 与 `perception.py`，复用 `main.py`、`models.py`、`worker.py`。新增 `0007_media_analysis.py`，持久化 `media_analyses`、`analysis_revisions`，保留既有任务与创作表。
- 前端新增 `MediaAnalysis.vue`、`AnalysisReview.vue`、`AnalysisWaveform.vue`、`analysisApi.ts`，接入现有素材入口和剧情改编。
- 验收更新 `test_media_analysis.py` 及历史迁移断言，增加 `browser-p6.mjs`、通用 Chrome 辅助模块和 `p6_recovery_check.py`。更新隔离回归脚本、回环 Vite 代理配置和 Windows 进程时间身份对比。实际验证过程发现 PowerShell 7 会解析 JSON 时间类型，启停现在比较 UTC 时间值，通过 PID 与可执行文件共同校验。

本地复验命令

```powershell
.\.venv\Scripts\python.exe scripts/isolated_regression.py --browser-phase p6 --browser --junitxml data/tmp/p6-backend-tests.xml
Set-Location frontend
npm.cmd run build
```

## 边界与回滚

- 当前样本覆盖常见容器与音视频流。代理预设仅处理 SDR 8-bit YUV，HDR 会保留原件并拒绝 SDR 代理。软字幕转换 SRT 会省略 ASS 样式，硬字幕、图像型字幕与混合音源的自动识别/分离待接入。浏览器可通过实际代理预览；容器原片播放取决于浏览器支持。
- 抽帧与切镜受 240 帧/镜头限制，分析按单 Worker 执行。未做完整解码器安全审计、极长片吞吐、采样之外全片 VFR 判定、磁盘低水位压力和 Windows reparse point 专项验证。
- 0007 有分析任务或快照时拒绝删表降级。回滚先停写并保留现库和数据，在独立库恢复 0006 备份与对应文件，校验完毕后使用 P5 代码和恢复库配置。现有原始素材及 0007 结果保留用于后续恢复。P7 下一步为故事圣经、跨集状态、角色固定参考和结构化分镜。
