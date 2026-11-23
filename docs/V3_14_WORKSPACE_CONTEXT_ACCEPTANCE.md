# 刀码漫剧 V3.14 制作定位验收

来源为《全系统整合与前后端重构总体方案》的 M00/M01。此次增量基于 `03647230650e2638e73aab7440f758e2a97bcd18`，在 `codex/v3-14-production-context` 分支验收。优先解决项目总览、生产调度、Guardian、固定分镜和生成候选间的定位与返回。

## 实际操作

1. 在有批准计划的项目总览中，通过「制作定位」选择分集和镜头，再点「继续当前镜头」。也可直接打开该集的固定分镜。
2. 从生产调度分集卡点「打开本集镜头审核」，在 Guardian 选择镜头并打开定位。使用原有的候选审核入口播放本机视频，再通过「返回原批次」回到原来的生产批次和分集卡。
3. 刷新深链接可恢复该定位。通过侧栏和全局搜索切换工作区时会保留定位。切换项目会清除旧范围。需要变更当前定位时，可选择其他分集或使用「清除制作定位」。更改定位时，当前工作区的编辑器按原业务链接保持实例和草稿。

## 数据与范围

- API `GET /api/projects/{project_id}/workspace-context` 读取同项目的批准故事圣经或指定生产批次，复用连续性报告解析分集、分镜、镜头和固定规格。跨项目、计划与批次冲突、镜头与分集冲突分别返回明确错误。历史批准版按原来的固定规格回读。已有批准门禁仍控制实际生产。
- 共享定位通过 `focusPlan`、`focusEpisode`、`focusShot` 和 `focusRun` 保存在 URL。前端跳转到目标工作区时继续传递已有的 `version`、`shot`、`run` 和 `episode`，兼容旧深链接。查看和选择定位属于只读操作。
- 本轮使用 PostgreSQL `0018`，沿用现有数据结构、12 个一级导航、21 个业务路由和六阶段 24 步。无新增运行依赖或外部源码。依赖审查沿用仓库记录；外部候选项目的逐仓许可证审查、CI 扩充、导航整体重组和 Codex 执行仍待后续里程碑。 [现有依赖许可证审查](LICENSE_REVIEW.md)

## 变更文件

- 后端 `backend/app/workspace_context.py` 和 `main.py` 提供项目内定位读取接口。
- 前端 `WorkspaceFocus.vue`、`WorkbenchLayout.vue`、`App.vue`、`router/productionFocus.ts`、`router/workspace.ts` 提供共享显示、路由继承和同页草稿保留。`ProductionStudio.vue`、`ProductionPage.vue`、`GuardianPage.vue` 提供分集审核和返还交接。
- `test_workspace_context.py`、`scripts/browser-v3-spec.mjs` 和 `scripts/isolated_regression.py` 覆盖 API 项目隔离与固定输入、真实样片动线、独立前端构建预览。

## 实际验收

- 后端全量 **175 项通过，0 失败，0 跳过**，用时 276.30 秒。有一条已有的 Starlette/httpx 弃用提示。Vue 类型检查、Vite 生产构建与 Alembic 模型比对通过。 [JUnit](v3-14-backend.xml)
- Chrome 从项目总览选择镜头、刷新、打开固定分镜、通过侧栏切到导演、从实际生产批次进入 Guardian、播放 720×720 的 FFmpeg 候选，再回到原批次原分集。项目当前规格为 v4 时，仍展示原固定规格 v2；同页切换定位后未保存制作指令仍在。跨项目返回 404，批次与计划冲突返回 409，切换项目会清除旧范围。390 像素宽下定位区无横向溢出。 [截图](v3-14-workspace-context.png) · [浏览器记录](v3-14-context-browser.json) · [固定规格和交付](v3-14-spec-browser.json)
- Chrome 回归通过原有 12 个导航项与六阶段 24 步。Guardian 两集十镜实测返工 1 镜、复用 9 镜，核验 30 张交付证据帧。真实外部调用 0 次。 [兼容性回归](v3-14-legacy-browser.json)
- 在独立数据库和目录恢复验证 7 个项目、13 项素材和 120 个文件，恢复后的素材 Range 请求返回 206。稳定版仍在线，分支构建使用独立目录。 [备份恢复](v3-14-recovery.json) · [本机稳定版状态](v3-14-stable-runtime.json)

## 复验与回滚

```powershell
npm.cmd --prefix frontend run build -- --outDir ../data/tmp/v3-14-dist
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --junitxml data/tmp/v3-14-backend.xml
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-spec --browser-dist data/tmp/v3-14-dist --browser-evidence data/tmp/v3-14-v3-spec
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-01 --browser-dist data/tmp/v3-14-dist --browser-evidence data/tmp/v3-14-v3-01
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-guardian --browser-dist data/tmp/v3-14-dist --browser-evidence data/tmp/v3-14-v3-guardian
& ./.venv/Scripts/python.exe scripts/p6_recovery_check.py --stage image-candidates
```

验收使用独立前端产物和临时数据库。要撤销分支功能可回退其提交，或使用稳定基线 `0364723` 构建与启动。数据库继续使用 `0018`。旧的生产、审核和素材链接仍可使用。
