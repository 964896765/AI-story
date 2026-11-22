# V3 Guardian 单镜头返工

2026-11-22 基于 `88e20da` 增量交付。

1. 在 Guardian 选择当前批准的故事圣经和目标镜头，也可从版本影响分析定位。选择合同允许的参考图、画幅和运镜，填写返工原因。Worker 使用批准合同的帧数生成一条候选。
2. 打开候选审核，核对原图与 FFmpeg 抽出的三张证据帧。通过后采纳，再返回镜头返工。批准合同过期、素材不匹配、审核未通过、候选未采纳或文件损坏会阻断后续操作。
3. 选择同画幅的当前时间轴，填写替换说明并保存。系统在同一时间轴资产追加版本，只改目标片段的素材引用；同一故事圣经的新版合同符合旧时间轴布局时，可同时固定新版制作计划。镜头布局或音轨约束发生不兼容变化时，可到多轨工作台重新装配。
4. 新版本保留原时间轴版本、返工原因、候选、原素材和新素材的记录。其余片段、顺序、时长、音轨、字幕和历史文件保留。批次生产和授权交付使用实际引用的素材。

## 验收

- Chrome 使用两名虚构角色、两个场景和十个真实生成镜头。只重做第 2 集第 5 镜，九个原镜头继续使用原候选。浏览器完成影响定位、候选生成、证据审核、采纳与时间轴替换。相比原时间轴，目标片段只更新素材引用，同集四个片段逐项一致。之后实际渲染、质检、离线配音及授权 ZIP 下载通过。四类视觉错误由人工审核记录退回。 [返工界面](guardian-shot-rework.png) · [浏览器记录](guardian-shot-rework-browser.json)
- 后端专项验证同合同替换、非锁定源图、重复请求、过期任务、未审候选、候选损坏及原音轨保留。两镜时间轴使用 FFmpeg 实际合成，成片通过检查并具有音轨。真实外部模型费用为 0 元。
- 后端全量 142 项通过，0 失败、0 跳过，用时 199.34 秒。首次全量运行发现新增测试样本缺少必填正史事实，补齐后专项及最终全量通过。Alembic 模型比对、Vue 类型检查与 Vite 生产构建通过。AI 总导演两集生产、分集返工与交付 Chrome 回归通过。
- 交付验收确认被替换的旧片段未列入新成片的授权检查。上线前用独立库与目录恢复 `0015` 的 7 个项目、13 项素材、120 个文件，素材 HTTP Range 返回 206。新版 Guardian 返回 HTTP 200，Worker 在线。 [恢复记录](guardian-shot-rework-recovery.json) · [本机就绪](guardian-shot-rework-readiness.json)

## 源码与复验

- 后端涉及 `backend/app/generation.py`、`guardian.py`、`series.py`、`timeline.py`。存储复用 `Task`、`TaskEvent`、`StoryVersion` 和资产引用，数据库使用 `0015`。
- 前端涉及 `frontend/src/pages/GuardianPage.vue`、`GenerationPage.vue`、`frontend/src/GenerationStudio.vue` 和 `frontend/src/components/production/GuardianShotRework.vue`。
- 测试涉及 `backend/tests/test_guardian.py` 与 `scripts/browser-v3-guardian.mjs`。

在工程根目录执行。浏览器验收在独立 PostgreSQL 和文件目录中运行。

```powershell
npm.cmd --prefix frontend run build
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --junitxml data/tmp/guardian-rework-final-backend.xml
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-guardian --browser-evidence data/tmp/guardian-shot-rework-final
# 本机尚未启动时使用
& ./scripts/start.ps1 -Production
```

## 范围与回滚

适用本机静图运镜，并保留逐镜人工审核。视觉语义自动诊断、模型驱动的导演规划和付费模型仍待验证。

确认本机队列空闲并备份当前数据后运行 `scripts/stop.ps1`。反向提交本批源码后重新构建，运行 `scripts/start.ps1 -Production`。没有新增数据库迁移，已生成候选与新时间轴按现有素材和版本格式保存。仅撤回某次镜头替换时，可在多轨工作台选择历史版本并追加恢复版本。
