# V3 Guardian 对白与背景声质检

基于 `cc58933` 增量开发。数据库沿用 `0015`，分轨报告随分集技术质检写入现有任务输出，也随交付包的 `quality.json` 保存。

## 规则与操作

- 新批次遇到与对白重叠的音乐或音效时，Worker 复核固定素材哈希，按时间轴的入点、位置、音量和淡入淡出还原限幅前对白与背景分轨，并测量立体声能量。已有成片可从「使用当前规则复检」运行。没有有效重叠时无需分轨测量。
- 对白活动区按 100 毫秒块测量。背景达到 −50 dBFS 且对白比背景高不足 6 dB 持续至少 300 毫秒时，记录最长一段供回听。对白分轨信号过低或源素材无法验证时也会提示人工复核。测量是本地电平规则，语义理解、分离成片中的音源和口型对齐仍待验证。
- 在「生产调度 → 固定对白核验」点击「回听混音」定位实际成片。用「定位关联片段」打开固定版时间轴，调整背景轨音量并另存新版本，再回到原批次做分集返工。检测到遮盖的批次须先完成复核或返工才能交付。

## 实际验收

- 163 项后端测试通过，0 失败、0 跳过，用时 175.81 秒。用真实 FFmpeg 音频测量了强背景、低背景和素材哈希不符三种情况。另覆盖立体声反相、停顿和短噪声。空库升级及 Alembic 模型比对、Vue 类型检查和 Vite 生产构建通过。保留 1 条 Starlette/httpx 上游弃用提示。 [JUnit](guardian-balance-backend.xml)
- Chrome 使用两集十镜和实际 Windows 本机配音，在第五镜叠加 FFmpeg 生成的测试音。报告定位到 5.100–6.600 秒，对白 −27.9 dBFS、背景 −14.5 dBFS，电平差 −13.4 dB。播放定位和背景片段焦点均通过。未复核的批次提交交付返回 409。 [审片截图](guardian-dialogue-balance.png)
- 首次把测试背景轨调整到 0.05 后，报告仍找到 300 毫秒的低余量。允许更细的输入后，在浏览器调整到 0.01 并保存新版本。重新制作第一集后告警消失，第二集复用原质检，旧批次仍保留原告警。下载的 ZIP 为 927,494 字节，SHA-256 与回执一致，内含 `guardian-dialogue-balance-v1`。P11 的真实黑场定位、返工与重渲染浏览器回归也通过。 [浏览器记录](guardian-balance-browser.json)
- 在独立 PostgreSQL 和文件目录恢复了 `0015`，核对 7 个项目、13 项素材和 120 个文件，素材 Range 请求返回 206。 [恢复记录](guardian-balance-recovery.json)
- 确认队列空闲后重启本机应用，生产调度和 Guardian 返回 200，新版混音界面已加载，1 个 Worker 在线。真实 API 调用和外部模型费用均为 0。 [本机就绪记录](guardian-balance-readiness.json)

## 修改文件

- Worker 质检与复用 `backend/app/guardian_balance.py`、`quality.py`、`production.py`、`timeline_render.py`。
- 工作台 `frontend/src/ProductionStudio.vue`、`TimelineStudio.vue`、`analysisApi.ts`。轨道音量允许保留细于 0.05 的设置。
- 验收 `backend/tests/test_guardian_balance.py`、`scripts/browser-v3-guardian.mjs`，以及本记录和实测证据。

## 复验与回滚

```powershell
npm.cmd --prefix frontend run build
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --junitxml data/tmp/guardian-balance-backend.xml
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-guardian --browser-evidence data/tmp/guardian-balance
```

需要回滚时，等待队列空闲并备份。用 `scripts/stop.ps1` 停止项目服务，对本批独立提交执行 `git revert`，重新构建前端后用 `scripts/start.ps1 -Production` 启动。数据库继续使用 `0015`，历史版本、审片记录和已有 ZIP 保留，回滚后按前一版质检规则执行。
