# V3.0 第二阶段 · 智能解析工作台

基线为 `3582a60`。本批交付覆盖“项目与素材 → 智能解析”。其余专用工作区继续按后续批次处理。

桌面版将播放与源时间轴置于左栏，解析参数、队列筛选和日志置于右栏，手机使用单栏。镜头按钮、关键帧、字幕和波形可定位播放器。字幕每页 50 条，可选字幕轨并显示当前字幕。完成流清单后，每个适用的操作可选择自己的源流，Worker 按所选索引执行。

定位链接包含项目、素材、解析任务、微秒时间和实际使用的代理任务。打开后可恢复原解析结果和旧代理，即使已有更新产物。浏览器无法解码原素材时可使用已生成的 MP4 代理。历史解析任务的只读查询同时校验任务种类与项目、素材归属，旧记录即使不在队列首页也可打开。

## 验收

- 独立 PostgreSQL 库升级到 `0013`，`alembic check` 通过。后端 123 项通过，0 失败，0 跳过，有一条既有的 Starlette httpx 弃用提示。新增用例覆盖同一任务在排队和成功时的读取，以及项目、素材不匹配时返回 404。 [JUnit](v3-02-backend-tests.xml)
- `vue-tsc` 和 Vite 生产构建通过。Chrome 生产构建的 12 条流程全部通过，包含 V3 总览和 P5 至 P14 的历史流程，以及独立 OCR 流程。首轮开发服浏览器检查仅提交 1 个步骤，其原因是导航后的控件未完全就绪。脚本改为逐步等待勾选状态后复验通过。
- 自制 MKV 的 8 种本地 FFmpeg 操作成功，第二音轨由 Worker 实际生成波形。52 条软字幕可翻页，选字幕会移动播放头，点击第二个镜头会跳到 1 秒。生成新代理后重开旧链接，浏览器仍加载旧代理，并选中原字幕任务和 1 秒位置。已检查 1440 桌面和 390 移动截屏。审核快照和 P5 固定剧本接力成功，原素材 SHA-256 匹配，JS 异常 0。 [结构化结果](v3-02-analysis-browser.json) · [桌面截屏](v3-02-analysis-desktop.png) · [移动截屏](v3-02-analysis-mobile.png)
- 将本机 `0013` 数据库及 120 个生产存储文件恢复到独立数据库和目录，复核 7 个项目、13 项素材、文件哈希和素材 HTTP Range 206。此次无表结构变更，回滚无需迁移。 [恢复记录](v3-02-recovery.json)
- 真实 API 预算 0，真实付费模型调用 0。语音转写、说话人分段、音源分离和语义理解仍显示待接入。

## 文件与复验

- `frontend/src/MediaAnalysis.vue`、`analysisApi.ts`、`pages/AnalysisPage.vue` 提供审片界面和定位链接。
- `backend/app/analysis_routes.py` 查询历史解析任务。带范围验证的用例在 `backend/tests/test_media_analysis.py`，实机用例在 `scripts/browser-p6.mjs`。

```powershell
Push-Location frontend
npm.cmd run build
Pop-Location
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --v3-browsers --junitxml data/tmp/v3-02-backend-tests.xml --browser-evidence data/tmp/v3-02
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1 -Production
```

回滚时先确认本机队列空闲，再通过项目停止脚本停服务。使用独立检出中的 `3582a60` 源码和锁文件构建、启动，连接原 `0013` 数据库和存储目录。已保存的解析和审核记录可继续读取，回滚期间使用素材入口查看历史。
