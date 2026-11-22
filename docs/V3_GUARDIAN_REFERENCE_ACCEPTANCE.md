# 刀码漫剧 V3 固定参考图对照

基于 `21feb8d` 增量开发，沿用数据库 `0015`、既有镜头合同和候选审核记录。外部模型调用与费用均为 0。

## 使用与规则

1. 先在角色、场景或故事圣经风格中登记参考图，纳入已批准的故事圣经。候选审核的「固定参考对照」会显示镜头要求，并提供批准版本对应的参考图。
2. 选择参考图和候选证据帧，使用「预览对照时点」查看实际视频。可点击「附到内容审核」，让这组对照跟随通过或退回记录保存。退回时，对照帧与问题证据帧须一致。
3. 服务端核对候选绑定的合同哈希、参考图所在项目、固定图片哈希及候选证据帧。参考文件缺失或内容被改动时，无法作为新的审核附件。已保存的对照可在候选审核和 Guardian 读取，采纳后的对照片段索引、哈希和固定版本写入 ZIP 中的 `guardian.json`。
4. 每条审核可选附一组对照，历史审核仍可查看。审核人依据画面决定角色外观、服装、道具和场景有无问题。通用视觉语义模型仍待接入。

## 实际验收

- 两集十镜 Chrome 流程用真实运镜候选对照原创角色图。定位到 0.500 秒后，将阿青 v1 的角色参考与错误样帧附到退回记录，采纳请求返回 409。另将灯塔外 v1 的场景参考与正确候选的 0.500 秒画面附到通过记录。Guardian 重新打开后显示该对照。成片实际下载的 ZIP 为 1,041,354 字节，核对哈希与 `guardian.json` 中的对照记录。 [对照截图](guardian-reference-compare.png) · [浏览器记录](guardian-reference-browser.json)
- 专项使用真实图片和实际生成的证据帧，覆盖正确文件、越界引用、退回帧不一致、同长度文件篡改、幂等重复审核和计划换版后的历史读取。
- 首轮全量在上批配乐压低测试里发现一次片尾提前静音。将压缩器两路输入统一为等长采样块和采样时间戳，整剧渲染与 Guardian 复测共用修复。用真实四秒 MP4 重复检查 40 次，片尾配乐信号均符合阈值。只读检查显示本机正式库没有启用配乐压低的已发布成片。 [片尾回归记录](guardian-reference-mix-stress.json)
- 修复后全量后端 165 项通过，0 失败、0 跳过，用时 186.15 秒。空库升级、Alembic 模型比对、Vue 类型检查、Vite 生产构建和 P8 候选制作与采纳的 Chrome 回归均通过。保留 1 条 Starlette/httpx 上游弃用提示。 [JUnit](guardian-reference-backend.xml)
- `0015` 在独立数据库和目录实际恢复，核对 7 个项目、13 项素材和 120 个文件，素材 Range 返回 206。 [备份恢复记录](guardian-reference-recovery.json)
- 队列空闲后更新本机服务，候选审核和 Guardian 均返回 200，参考对照接口可用，1 个 Worker 在线，付费开关关闭。 [本机就绪](guardian-reference-readiness.json)

## 修改文件

- 后端 `backend/app/generation.py`、`guardian.py`、`series.py`。复用现有 `guardian_review` 和 `guardian.json`。
- 前端 `frontend/src/components/production/GuardianReferenceCompare.vue`、`GenerationStudio.vue`、`pages/GuardianPage.vue`。
- 验收 `backend/tests/test_guardian.py`、`scripts/browser-v3-guardian.mjs`、本记录及实测证据。
- 混音回归修复 `backend/app/timeline_render.py`、`backend/tests/test_timeline_ducking.py`。

## 复验与回滚

```powershell
npm.cmd --prefix frontend run build
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --junitxml data/tmp/guardian-reference-final-backend.xml
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-guardian --browser-evidence data/tmp/guardian-reference
```

需要回滚时，等待本机任务完成并备份数据库和生产文件，然后用 `scripts/stop.ps1` 停止服务。对「固定参考图对照」的独立提交执行 `git revert`，重新构建前端并用 `scripts/start.ps1 -Production` 启动。数据库仍为 `0015`，已有对照保留在历史审核与已生成的 ZIP 中。配乐片尾修复采用单独提交。
