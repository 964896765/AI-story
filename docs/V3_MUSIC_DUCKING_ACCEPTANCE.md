# 刀码漫剧 V3 对白时压低配乐

基于 `2a33dab` 增量开发。数据库沿用 `0015`。使用当前 FFmpeg 的 `sidechaincompress`，本阶段外部模型调用与费用均为 0。

## 操作与行为

1. 在「剪辑与时间轴」添加启用且有音量的对白轨和音乐轨。勾选「对白时压低配乐」并保存时间轴新版本，再按原流程渲染或提交整剧生产。
2. 渲染时由剪辑后的对白电平驱动音乐轨的动态压低。预设采用 15 毫秒起效、320 毫秒释放，随后保持时间轴原有整体限幅。对白、音效和非混音部分的剪辑参数沿用已固定版本。轨道条件不足时报告「未启用」原因。
3. Guardian 使用同一 FFmpeg 配乐处理还原限幅前分轨，检查压低后的音乐和音效是否仍可能盖住对白。出现告警时可回听成片和定位相关片段。处理预设写入成片任务及授权 ZIP 的分集 `quality.json`。
4. 选项默认关闭。未启用版本沿用旧 JSON 和原渲染策略，已发布历史成片保留原哈希。这个预设依据对白信号起效，背景噪声过强或台词电平过低时仍需审片调整。声音身份和画面口型仍待验收。

## 实际验收

- Chrome 使用两集十镜和真实本机配音。初始混音在 5.100–6.600 秒检测到背景高出对白 1.3 dB。在剪辑工作台勾选选项，音乐轨音量维持 0.25。保存新时间轴，只重新制作第一集后，该段遮盖告警消除。第二集复用上一批的质检结果，旧批次保留原告警。 [剪辑界面](guardian-ducking-settings.png)
- 授权 ZIP 实际下载 1,033,390 字节，SHA-256 与回执一致，分集质检留有 `ffmpeg-sidechain-dialogue-v1`。旧批次未经复核返回 409。P11 原有浏览器返工与重新合成流程回归通过。 [浏览器记录](guardian-ducking-browser.json)
- 独立的 MP4 测试使用三种可区分的测试音，解码成片后确认对白期间配乐下降 27.0 dB，前后配乐恢复到未开启时的电平容差内，对白和音效分量通过稳定性检查。素材哈希一致，同一任务再次执行返回已验证成片。
- 165 项后端测试通过，0 失败、0 跳过，用时 184.69 秒。空库升级、Alembic 模型比对、Vue 类型检查和 Vite 生产构建均通过。保留 1 条 Starlette/httpx 上游弃用提示。 [JUnit](guardian-ducking-backend.xml)
- `0015` 数据库和文件恢复至独立环境，核对 7 个项目、13 项素材和 120 个文件，素材 Range 206。 [备份恢复记录](guardian-ducking-recovery.json)
- 确认队列空闲后更新本机服务。时间轴 HTTP 200，新功能加载，1 个 Worker 在线，外部调用关闭且预算为 0。 [本机就绪记录](guardian-ducking-readiness.json)

## 修改文件

- 后端 `backend/app/story_schemas.py`、`timeline_render.py`、`guardian_balance.py` 和 `quality.py`。
- 前端 `frontend/src/TimelineStudio.vue`、`ProductionStudio.vue`。
- 验收 `backend/tests/test_timeline_ducking.py`、`scripts/browser-v3-guardian.mjs`、本记录及验收证据。

## 复验与回滚

```powershell
npm.cmd --prefix frontend run build
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --junitxml data/tmp/guardian-ducking-backend.xml
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-guardian --browser-evidence data/tmp/guardian-ducking
```

需要回滚时，先等待本机队列空闲并备份当前数据库与生产文件，再用 `scripts/stop.ps1` 停止服务。尚未保存启用该选项的版本时，可以 `git revert` 本批提交，重新构建后运行 `scripts/start.ps1 -Production`。已保存启用版本的项目，回滚前先把升级前快照恢复至独立的 `0015` 库和文件目录，验证后切换。保留含新时间轴版本与成片的当前备份，以便恢复新版后继续制作。
