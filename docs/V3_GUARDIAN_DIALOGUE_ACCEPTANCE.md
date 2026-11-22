# V3 Guardian 成片对白质检

基于 `8d81d00` 增量开发。数据库仍为 `0015`，复用现有固定版本、Worker、审片、复检和交付流程。使用本机 FFmpeg 和已安装的 Windows 简体中文听写，本批外部调用 0 次，外部模型费 ¥0。

## 使用与结果

1. 在整剧时间轴使用同一项已采纳的本机配音任务产出的音轨和字幕。提交时核对批准分镜、固定说话者、音色、文字、时间和两份素材哈希。混用配音与字幕的请求返回 422。
2. 在「生产调度 → 提交整剧批次 → 技术质检阈值」或「AI 总导演」可选已安装的对白听写语言。字幕和静音检查随受 Guardian 约束的分集执行。
3. 成片字幕按发布哈希、对白文字和毫秒时段核验。缺失、额外或不一致的字幕会阻断交付。Worker 解码实际 AAC 混音，计算对白窗口内最响 20 毫秒块的 RMS，低于 −55 dBFS 阻断交付，时间轴对白轨音量为零也会阻断，即使背景音仍然可听见。
4. 在分集报告展开「固定对白核验」，查看批准文本、固定音色、字幕状态、混音电平和听写。点「回听」跳到成片对应时间。听写不一致、没有识别结果或本机语言不可用时，需人工回听。阻断项必须先返工。交付 ZIP 的分集 `quality.json` 保存对白结果和复核记录。
5. 已完成的历史批次如缺少对白报告，创建新交付包前可点「使用当前规则复检」沿用原成片。既有交付包继续执行原有的授权和文件校验。

## 实际验收

- Chrome 从生产表单选择简体中文并提交两集十镜。第五镜的批准对白与实际发布字幕一致，证据区间为 4.000–7.330 秒，最响块为 −16.01 dBFS。点击回听定位到 4.000 秒。实际下载的 ZIP 为 885,843 字节，SHA-256 与交付回执一致，包含 `guardian-dialogue-v1` 报告。 [浏览器记录](guardian-dialogue-browser.json) · [实际工作台](guardian-dialogue-review.png)
- 故意混用不同的配音和字幕任务，提交返回 422。故意把对白轨音量置零后，真实视频仍能成功渲染，质检在 4.000 秒报告静音并切换为需返工。人工通过和 ZIP 提交均返回 409，未变更的第二集复用成片。后端另用带背景音的真实媒体验证对白轨静音和字幕内容、时段不符仍会阻断。
- 本机听写把「欢迎来到灯塔」的一部分误听为「欢迎来稿等他」。正确样本因此产生一条需要复核的听写告警。静音样本没有返回文本。测试样本用于验证关卡和证据链，尚未统计跨题材、音色或背景音的识别准确率。
- 全量后端 159 项通过，0 失败、0 跳过，用时 182.08 秒。保留 1 条 Starlette/httpx 上游弃用提示。空库升级及 Alembic 模型比对、Vue 类型检查、Vite 生产构建均通过。另通过 AI 总导演整剧生产与分集返工、P12 授权交付两条 Chrome 回归。 [JUnit](guardian-dialogue-backend.xml)
- 在独立 PostgreSQL 和目录恢复现有 `0015`，核对 7 个项目、13 项素材、120 个文件及哈希，素材 Range 请求返回 206。 [恢复记录](guardian-dialogue-recovery.json)
- 确认队列空闲后重启本机生产构建。生产调度和 Guardian 页面均返回 200，数据库和 1 个 Worker 就绪，`zh-CN` 可用，真实接口开关关闭且预算为 0。 [本机就绪记录](guardian-dialogue-readiness.json)

## 主要文件

- `backend/app/guardian_audio.py`、`guardian.py`、`production.py`、`quality.py`、`worker.py`、`perception_asr.py`、`director.py`、`delivery.py`、`distribution.py`。
- `frontend/src/ProductionStudio.vue`、`LibraryDelivery.vue`、`analysisApi.ts`、`components/production/DialogueRecognitionField.vue`、`components/production/DirectorBatchFields.vue`、`pages/DirectorPage.vue`。
- `backend/tests/test_guardian_audio.py`、`scripts/browser-v3-guardian.mjs`、本记录和对应截图、浏览器与恢复证据。

## 复验与回滚

```powershell
npm.cmd --prefix frontend run build
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --junitxml data/tmp/guardian-dialogue-backend.xml
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-guardian --browser-evidence data/tmp/guardian-dialogue
& ./scripts/start.ps1 -Production
```

需要回滚时，先等本机队列空闲，备份数据库和生产文件并保留其他工作区修改。用 `git revert` 反向提交本次开发提交，然后重新构建并启动。现有历史任务与报告保留在 `0015` 中。回滚后的新交付按上一版质检规则执行。需要复现升级前的工作状态时，可将升级前快照恢复到独立库和目录后切换。

对白窗口的电平来自整段混音。背景音过强、混音存在非零但过低的对白等情况仍需结合听写和实际回听判断。实际声纹、说话人身份和口型同步待验收，跨题材音频质检样本待补充。
