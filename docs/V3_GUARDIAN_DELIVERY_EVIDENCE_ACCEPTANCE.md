# 刀码漫剧 V3 Guardian 审核证据交付

基线为 `3146e5d`。使用现有 Worker、授权校验和 PostgreSQL `0015`。真实付费模型调用与费用均为 0。

## 使用与规则

1. 在「质检与交付 → 资源与交付」选择通过质检的批次，核对目标授权，提交交付包。任务成功后，页面显示随包保存的证据帧数量。
2. 解压 ZIP 后，`guardian.json` 按分集和镜头记录候选任务、内容审核、证据时间点、SHA-256 和 JPEG 相对路径。逐项审核及参考图对照中的候选帧可用索引和哈希定位到对应 JPEG。证据文件在 `episode-NNN/guardian/shot-NNN/` 下，也列入 `manifest.json`。
3. Worker 只收录交付时间轴实际采用的候选证据帧，并在写入和回读 ZIP 时校验字节。文件缺失或哈希不符时记录具体镜头和证据索引。恢复同一份证据后，可在交付页重试原任务。原始参考图继续保存在本机工作台。
4. 既有 ZIP 保留发布时的内容和哈希。旧包需要证据图片时，可为合格批次创建新交付。实际视觉语义模型仍待接入，证据用于人工复核。

## 实测

- Chrome 使用两集十镜的 FFmpeg 自制样片。移除一张证据帧、换成大小相同的被改动文件，两次交付均失败且下载返回 409。恢复原 JPEG 后，在页面重试同一个任务，成功下载唯一的 1,652,407 字节 ZIP。实际解压并核对 30 张 JPEG、两份清单和整包 SHA-256。逐项审核及参考对照引用均能定位到包内 JPEG，无 JavaScript 错误。首轮脚本在重试请求完成前读到了上次失败，调整为等待第三次尝试后复验通过。 [失败截图](guardian-delivery-evidence-error.png) · [成功截图](guardian-delivery-evidence.png) · [浏览器记录](guardian-delivery-evidence-browser.json)
- 普通交付的 Chrome 回归通过，覆盖缺授权拦截、授权后真实 ZIP 下载与人工发行交接。 [P12 回归](guardian-delivery-evidence-p12.json)
- 后端 165 项通过，0 失败、0 跳过，190.56 秒。空库迁移到 `0015`、Alembic 模型检查、Vue 类型检查、Vite 生产构建通过。保留一条 Starlette/httpx 上游弃用提示。 [JUnit](guardian-delivery-evidence-backend.xml)
- `0015` 在独立数据库和独立目录实际恢复。核对 7 个项目、13 项素材及 120 个文件的哈希，恢复后的素材 Range 请求返回 206。队列空闲时更新本机服务，交付页返回 200，1 个 Worker 在线，真实调用禁用，默认预算 0。 [备份恢复](guardian-delivery-evidence-recovery.json) · [本机就绪](guardian-delivery-evidence-readiness.json)

## 修改文件

- `backend/app/delivery.py` 负责收集、校验、打包与记录证据帧。
- `frontend/src/LibraryDelivery.vue` 显示写入的证据数量并提供失败任务重试。
- `scripts/browser-v3-guardian.mjs` 覆盖异常证据、同任务重试和实际解包。
- `README.md`、`docs/ACCEPTANCE.md`、本记录及关联实测证据。

## 复验与回滚

```powershell
npm.cmd --prefix frontend run build
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --junitxml data/tmp/guardian-delivery-evidence-backend.xml
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-guardian --browser-evidence data/tmp/guardian-delivery-evidence
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase p12 --browser-evidence data/tmp/guardian-delivery-evidence-p12
```

要回滚时，等待任务结束、备份数据库及生产文件，运行 `scripts/stop.ps1`。对本次「Guardian 审核证据交付」提交执行 `git revert`，重新构建后运行 `scripts/start.ps1 -Production`。数据库沿用 `0015`。已发布的 ZIP 可通过同一交付任务读取，仍受原授权与成片质检要求约束。
