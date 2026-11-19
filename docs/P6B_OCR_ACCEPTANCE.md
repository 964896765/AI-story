# P6-B Windows 本机画面文字识别

基线为 P14 提交 `0877563`。本轮补齐使用已安装 Windows OCR 识别器的视频画面文字采样，含镜头证据、人工修订及正式剧本采纳。测试在 2026-11-19 执行。

## 实现与迁移

- “智能解析”从本机能力探测列出 OCR 语言。选择视频、识别语言和采样间隔后，Worker 用 FFmpeg 取真实采样帧，调用本机 OCR 并写入文本、行、帧索引和容器原点微秒时间。
- 任务固定源素材 SHA-256、所选语言、OCR 适配器和 Windows 版本。可复用的 OCR 产物仍重新核对哈希。语言未安装时返回明确错误，原件独立保存。
- 审核快照可将 OCR 采样关联所在镜头。人工可依据采样帧修改正文及实际时段，校对后的文字通过确认动作进入固定 P4 剧本，再作为 P5 原稿。原识别和人工校对均可回查。
- 使用现有异步解析任务、`media_analyses` 与 `analysis_revisions` JSON 字段。Alembic 保持 `0013`，模型比对无差异。历史结果与审核快照继续读取。

修改 `analysis_engine.py`、`analysis_schemas.py`、`analysis_service.py`、`analysis_routes.py`、`analysis_review.py` 和 `perception.py`，新增 `perception_ocr.py` 与 `scripts/recognize_frames.ps1`。工作区更新 `MediaAnalysis.vue`、`AnalysisReview.vue`、`analysisApi.ts`，复验覆盖 `test_media_analysis.py`、Chrome 和 `isolated_regression.py`。

## 验收

- 真实自制视频共两秒，第一秒以字体绘制“灯塔坐标”，第二秒纯黑。真实识别在 0 秒取到中文，1 秒采样为空。本机资产哈希不变，已检查采样帧下载哈希、结果复用、未知语言拦截和镜头对齐。
- Chrome 实际提交任务，显示识别文字及采样位置，人工修订为“灯塔坐标（已按画面校正）”，保存快照后将修订文字作为固定剧本，P5 页面打开该原稿。无 JS 异常。 [浏览器证据](p6-ocr-browser-acceptance.json) · [实际审核截图](p6-ocr-review.png)
- 首轮专项的幂等断言比较了两次请求的完整序列化对象，实际上只需核验是否重用同一任务。修正为核对有序任务 ID 后，专项 6 项通过。独立全量 **121 项通过，0 失败，0 跳过**，保留 1 条 Starlette/httpx 上游弃用提示。生产构建的 P5–P14 共 11 条浏览器流程全部通过，包含本轮 OCR。 [后端证据](p6-ocr-backend-tests.xml)
- `vue-tsc`、Vite 生产构建、独立 Alembic 检查和 `pip check` 通过。真实 API 调用 0 次，本次支付 0 元。Windows 识别器和字体由本机提供，未下载模型。 [Windows OCR API](https://learn.microsoft.com/en-us/uwp/api/windows.media.ocr.ocrengine)

```powershell
Push-Location frontend
npm.cmd run build
Pop-Location
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --all-browsers --junitxml data/tmp/p6-ocr-backend-tests.xml
```

## 限制与回滚

- 已实测 `zh-Hans-CN`，其他语言以系统实际安装情况为准。每次最多 120 帧，使用单次固定间隔采样。采样可能遗漏短时文字。时间点只表示该帧，字幕起止需校对确认。Windows OCR 语言可用性在进程启动后的首次探测时读取，系统识别器变化后需重启本机应用。
- 尚未接入 ASR、说话人分段、音源分离与视觉语义理解。本轮没有在系统语音识别组件中查到已安装的语音转写识别器。
- 回滚时先停写，保留数据库及存储。P14 代码可继续查看已有的非 OCR 分析结果与创作资产。保留已产生的 OCR 结果和快照，待需要读取及重跑 OCR 时重新启动含该功能的版本。没有 DDL 降级步骤。
