# V3 Guardian 画面文字核验

2026-11-23 基于 `a9a66b7` 增量交付。此次使用已安装的 Windows 简体中文识别器，实际外部调用和支出为 0。

## 使用与规则

1. 在「分镜编辑」的镜头合同内打开「画面文字核验」，填写识别语言、必现及禁现文字。保存分镜新版本后，在故事圣经引用这个版本并批准。只有登记规则的镜头会运行本次 OCR。
2. 候选制作时复用原有 FFmpeg 证据帧和 Windows OCR，记录识别引擎、语言、系统版本、原文、时间、证据帧哈希和候选视频哈希。匹配忽略空白和大小写并使用 NFKC 规范化，在同一识别行内查找文字。必现文字至少须在一个采样帧中识别到，禁现文字在任何采样帧识别到都会提示。
3. 在候选审核或 Guardian 查看报告并定位证据。发现差异、语言缺失或识别未完成时，可退回，也可在对照实际画面后明确记录人工核验。通过后才可采纳。原有全黑阻断优先。
4. 报告绑定批准合同和候选输出。已采用镜头的报告随授权 ZIP 内的 `guardian.json` 保存。未登记文字规则的旧合同保持原有哈希和历史可读性。

## 实测

- Chrome 在第二集第五镜实际保存新的文字规则，批准整剧版本后以 FFmpeg 制作正反两条候选。Windows OCR 在正确候选的三个采样帧识别到「灯塔坐标」，在错误候选中识别到「旧版标识」。错误候选同时报告未识别到必现文字和识别到禁现文字。两条自制样例上未观察到误报或漏报。
- 浏览器实际跳到 0.500 秒核对帧，绕过人工确认的通过请求返回 409，随后按证据退回。正常候选完成审核、采纳、只替换第五镜并通过两集生产和授权 ZIP 下载。ZIP 中检查到了实际核验报告。 [错误候选截图](guardian-screen-text.png) · [正反样本与交付记录](guardian-ocr-browser.json)
- 后端验证未安装语言时只保留实际视觉证据，要求明确人工确认；错误输入、重复或互相冲突的规则会被拒绝。人工确认无法解除原有全黑阻断。
- 全量后端 155 项通过，0 失败、0 跳过，用时 178.13 秒。Alembic 模型比对、Vue 类型检查和 Vite 生产构建通过。P6 原有 OCR 浏览器回归通过，包括硬字幕提取、镜头证据、人工修订与移交。保留 Starlette/httpx 上游弃用提示。
- 上线前在独立 PostgreSQL 和目录恢复本机 `0015`，核对 7 个项目、13 项素材、120 个文件和 HTTP Range 206。本机分镜与 Guardian 页面返回 200，Worker 在线，`zh-Hans-CN` 可用，付费开关关闭。 [恢复记录](guardian-ocr-recovery.json) · [本机就绪](guardian-ocr-readiness.json)

## 源码与复验

- 后端涉及 `backend/app/guardian_ocr.py`、`story_schemas.py`、`creative.py`、`guardian.py`、`generation.py`、`perception_ocr.py` 和 `delivery.py`。
- 前端涉及 `frontend/src/components/production/GuardianShot.vue`、`ScreenTextCheck.vue`、`frontend/src/GenerationStudio.vue`、`frontend/src/pages/GuardianPage.vue` 和 `frontend/src/analysisApi.ts`。
- 验收涉及 `backend/tests/test_guardian_ocr.py`、`test_guardian.py`、`scripts/browser-v3-guardian.mjs`。

```powershell
npm.cmd --prefix frontend run build
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --junitxml data/tmp/guardian-ocr-backend.xml
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-guardian --browser-evidence data/tmp/guardian-ocr-final
# 本机尚未启动时使用
& ./scripts/start.ps1 -Production
```

## 范围与回滚

采样可能遗漏停留极短的文字，模糊或被遮挡的文字仍需人工判断。此功能用于核对可见文字。角色身份、服装、道具和场景仍由人工审核，通用视觉语义模型和真实模型导演规划待接入。

数据库沿用 `0015`。队列空闲后备份当前库、生产文件和合同版本，再运行 `scripts/stop.ps1`。没有新增文字合同的库可反向提交本批代码、重新构建并启动。已有新增规则时，在独立库和目录恢复升级前快照，使用 `a9a66b7` 验证后切换，保留含新规则及报告的当前库和文件。
