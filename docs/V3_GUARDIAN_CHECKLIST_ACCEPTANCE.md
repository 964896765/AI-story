# 刀码漫剧 V3 逐项视觉审核

基于 `f983f90` 增量开发。沿用 PostgreSQL `0015`、现有候选审核和授权交付，外部调用与费用均为 0。

## 使用与规则

1. 在「分镜工作台」打开镜头合同，勾选「要求逐项视觉审核」，保存分镜新版本，并在故事圣经引用和批准该版本。开关默认关闭。启用会改变该镜头批准合同哈希，旧批准候选继续供历史查看。
2. 候选制作后，审核页根据批准合同列出画面构图、风格、场景和各角色身份、服装、适用的手持道具。服装与道具同时显示开场、收尾要求。逐项人工核对画面并选定通过证据帧，记录整条候选审核。可定位该帧并使用原有固定参考对照。
3. 服务端拒绝漏项、重复、未登记检查项和跨候选证据帧。已有技术拦截和文字人工核验继续生效。发现内容问题时可直接按原流程选问题类别和证据帧退回。完整结果保存合同哈希、检查项、预期内容、帧索引、时间和哈希，采纳后的证据写入交付 ZIP 的 `guardian.json`。
4. 审核需由人看片。所选证据帧记录审核依据，通用视觉语义、自动识别人物与衣着、逐帧内容检测仍待接入。

## 实际验收

- 后端专项覆盖候选无清单、漏项、重复项、合同外项目、不存在的候选证据帧，以及完整审核后采纳。重复提交同一组选项但调整顺序时返回原审核。保存的帧哈希与实际 JPEG 一致。
- Chrome 用两集十镜测试剧在第二集第五镜启用。跳过清单的通过请求返回 409。选择 0.500 秒和 0.958 秒的证据完成全部 8 项后，通过、采纳并替换该镜，另 9 镜复用。Guardian 能回读完整结果，并滚动到实际帧高亮显示。下载的 1,058,081 字节 ZIP 通过哈希校验，包含 `guardian-visual-checklist-v1`。 [审核截图](guardian-visual-checklist.png) · [浏览器记录](guardian-checklist-browser.json)
- 全量后端 165 项通过，0 失败、0 跳过，用时 187.75 秒。空库迁移、Alembic 模型比对、Vue 类型检查和 Vite 生产构建均通过。保留 1 条 Starlette/httpx 上游弃用提示。 [JUnit](guardian-checklist-backend.xml)
- 将 `0015` 快照恢复至独立数据库和独立文件目录，核对 7 个项目、13 项素材、120 个文件和文件哈希。实际读取恢复后素材，Range 返回 206。 [恢复记录](guardian-checklist-recovery.json)
- 在队列空闲时更新本机服务，候选审核、Guardian 页面均返回 200，逐项审核接口可用，1 个 Worker 在线，付费开关关闭且预算为 0。 [本机就绪](guardian-checklist-readiness.json)

## 修改文件

- 后端 `backend/app/story_schemas.py`、`guardian.py`、`generation.py`。
- 前端 `frontend/src/components/production/GuardianShot.vue`、`GuardianVisualChecklist.vue`、`GuardianReferenceCompare.vue`、`GenerationStudio.vue`、`pages/GuardianPage.vue`。
- 验收 `backend/tests/test_guardian.py`、`scripts/browser-v3-guardian.mjs`、本记录及实测证据。

## 复验与回滚

```powershell
npm.cmd --prefix frontend run build
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --junitxml data/tmp/guardian-checklist-backend.xml
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-guardian --browser-evidence data/tmp/guardian-checklist
```

回滚前等待任务结束，备份数据库和生产文件，并用 `scripts/stop.ps1` 停止本机服务。尚未保存启用版本时，可对本批提交执行 `git revert`，重新构建并用 `scripts/start.ps1 -Production` 启动。已保存启用版本时，保留当前备份，将升级前快照恢复至独立的 `0015` 和文件目录，确认后切换服务。已交付的 ZIP 仍保留原审核证据。
