# V3 Guardian 候选视觉技术检查

2026-11-22 基于 `39caad1` 增量交付。

- Worker 用 FFmpeg 按固定 24 fps 完整解码新建 Guardian 候选。96 × 54 灰度画面中至少 99% 像素值不超过 12 时记为近黑。全程近黑阻断通过和采纳，持续至少 6 帧的局部近黑需要人工复核。连续至少 18 帧与区间首帧的平均灰度绝对差不超过 0.35 时记录低变化提示。
- 报告包含规则版本、候选哈希、实际解码帧数、近黑帧数、发现时段和证据帧哈希。最多展示八段问题，并报告超出数量。证据帧可定位到候选播放器，也可作为人工退回证据。已采纳镜头的报告随 `guardian.json` 进入交付包。
- Guardian 和候选审核界面区分技术阻断与人工复核。过往候选若未记录逐帧检查，页面显示记录缺失。角色、服装、道具、场景继续由人审看。视觉语义模型尚未接入，外部模型费用 0 元。

## 实测

- 五段真实编码视频覆盖正常运动、全程近黑、局部近黑、静止和存在亮部的暗场。全程近黑阻断的样本结果为 1 个检出、0 个误阻断、0 个漏阻断。局部近黑定位到 0.500 至 0.958 秒，静止样本产生人工复核提示。本样本量仅用于规则回归。
- Chrome 在原两集十镜头 Guardian 流程额外制作了全黑候选。24 帧均达到近黑阈值，证据实际跳到 0.458 秒。尝试人工通过和采纳均返回 HTTP 409，退回保存了相同证据帧哈希。正常镜头继续完成返工、成片质检和实际 ZIP 下载，ZIP 可复核视觉检查规则版本。 [阻断截图](guardian-visual-blocked.png) · [浏览器记录](guardian-visual-browser.json)
- 最终后端全量 148 项通过，0 失败、0 跳过，用时 200.97 秒。Alembic 模型比对、Vue 类型检查与 Vite 生产构建通过。保留 Starlette/httpx 上游弃用提示。
- 上线前在独立库和目录恢复了本机 `0015`，核对 7 个项目、13 项素材及 120 个文件，素材 Range 请求返回 206。生产构建两个入口返回 200，Worker 在线。 [恢复记录](guardian-visual-recovery.json) · [本机就绪](guardian-visual-readiness.json)

## 源码与复验

- 后端涉及 `backend/app/visual_quality.py`、`generation.py` 和 `delivery.py`。逐帧报告存入已有任务输出及候选清单。
- 前端涉及 `frontend/src/GenerationStudio.vue`、`frontend/src/pages/GuardianPage.vue`、`frontend/src/components/production/VisualCandidateCheck.vue` 和 `frontend/src/analysisApi.ts`。
- 验收涉及 `backend/tests/test_visual_quality.py`、`backend/tests/test_guardian.py` 和 `scripts/browser-v3-guardian.mjs`。

```powershell
npm.cmd --prefix frontend run build
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --junitxml data/tmp/guardian-visual-backend.xml
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-guardian --browser-evidence data/tmp/guardian-visual-qa
# 本机尚未启动时使用
& ./scripts/start.ps1 -Production
```

## 回滚

队列空闲后备份数据库和生产文件，运行 `scripts/stop.ps1`，反向提交本批源码并重新构建，再运行 `scripts/start.ps1 -Production`。数据库使用 `0015`，没有新增迁移。已经保存的候选、人工审核和时间轴可按原格式读取。回滚后旧版程序按照原人工审核规则决定候选是否可采纳。
