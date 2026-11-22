# Production Guardian 本机验收

基于 `39ec9fc` 增量开发。界面使用用户补发的 `AI_Story_V3_PRISM_STUDIO_Web_UI_交互概念原型.html`，文件 SHA-256 为 `453fab0460bb17bb5effc1b5eed7d8982fb22fd2951630ee3164881955fd02a2`。本批将原型的分集问题列表、中央证据和版本检查器接入真实数据。浅色与深色主题应用于 Guardian 质量控制工作区。

## 实施范围

|阶段|可使用功能|证据或待验项|
|---|---|---|
|一 · 正史和版本|故事圣经固定总剧本及其小说来源、分集和分镜。锁定事实、角色身份与参考图、服装、场景、道具及风格。批准创建新版本并保存镜头合同哈希。|[规则与异常](guardian-backend-tests.xml)|
|二 · 连续性|检查同一角色的镜头开场、收尾、左右手道具、站位和动作，纳入跨集检查。状态变化附衔接说明后交人工核对。|[阻断界面](guardian-blocked.png)|
|三 · 视觉及音频证据|FFmpeg 验证本机候选，并抽取首帧、中段和末帧，记录时间和哈希。人工可按证据分类退回。对白使用批准的 Windows 离线音色，生成 WAV 和字幕。|[候选证据与审核](guardian-candidate-review.png)。真实语义视觉模型、独立图片生成及声纹判断待接入。|
|四 · 生产与返工|按批准合同验证输入、候选、画幅、帧数及对白版本。未通过人工内容审核的候选不能采纳。失效批准版本不能新提交或采纳。未变化的已批准镜头可跨同一故事圣经的新版本复用。整剧交付附 `guardian.json`。|[十镜头 HTTP 与浏览器流程](guardian-browser.json)|
|五 · 质量工作台|分集问题、首尾状态对照、帧证据、引用版本、生成与本地费用、合同变化分析。|[浅色工作台](guardian-prism-light.png) · [移动界面](guardian-mobile.png)。AI 总导演、六步向导和其他全站 PRISM 页面仍待实施。|
|六 · 本机原创试制|两名虚构角色、两个场景和十个镜头，包含离线配音、字幕、成片质检、授权拦截和 ZIP 交付。|[试制与交付证据](guardian-browser.json)|

## 操作

1. 在「角色与场景」保存人物身份锁，填写固定特征、服装键名，选择权利明确的参考图。需要对白时登记已安装的本机音色名称。
2. 在「分镜编辑」填写镜头合同，登记要出现的画面、事实、输入图片和角色首尾状态。在「故事圣经」启用 Guardian，选定人物、场景、分镜及剧本版本。对照规则结果，然后批准固定制作计划。
3. 在「质检与交付 → Guardian 质量控制」按分集核对问题。通过或退回生成中心中的候选。退回要填写问题类别、时间证据和说明。批准后可采纳，进入多轨时间轴。
4. 含对白的整集使用批准分镜对应的完整配音和字幕。整剧生产核对各镜头的合同、画幅与轨道范围，现有技术质检和授权门槛继续参与交付。

## 数据与验收口径

- 后端隔离库从空库升到 `0013` 并通过 `alembic check`。全量 138 项通过，0 失败，0 跳过，用时 164.87 秒。保留 Starlette/httpx 上游弃用提示。Vue 类型检查和 Vite 生产构建通过。 [JUnit](guardian-backend-tests.xml)
- 15 条 Chrome 流程通过。Guardian 用例检查了 390、1280、1440 和 1920 像素宽度下无横向溢出。用两集原创测试剧验证离线配音、字幕、成片质检、局部返工和 ZIP。一个镜头变更后有 9 个镜头可复用，只重做变化的一镜。735,156 字节的 ZIP 包含 Guardian 审核清单，下载后核对 SHA-256。 [Chrome 与交付记录](guardian-browser.json)
- 六集 720p 生产负载回归通过。总计 180 秒样片的渲染及质检耗时 39.89 秒，复用原成片复检耗时 5.403 秒。 [多集负载记录](guardian-load-regression.json)
- 使用现有 PostgreSQL `0013`。批准合同、证据清单与内容审核利用 `StoryVersion`、`Task`、`Asset` 的现有 JSON 字段和任务事件。成片技术检查和告警复核沿用原来的任务与 `QualityReview`。
- 自动规则在两条预标记阻断样例中检出两条，未出现额外阻断或漏报。四种错误视觉样本由验收脚本按预设标签记录人工审核决定。机器视觉误报、漏报和实际人工判断准确率均未测定。
- 已验证错误场景引用、未登记服装、左右手道具错位、动作衔接、剧情事实冲突、错音色、媒体损坏、审批过期和未审候选拦截。内容审核证据随 ZIP 交付并参与哈希核对。
- 本轮依赖现有 FFmpeg、Chrome 和 Windows 离线语音，付费调用和外部支出为 0。连贯性规则针对结构化声明。实际脸部身份、物体语义和跨镜头像素级一致性由人工对照，真实视觉模型仍待联调。
- 启动新版前对现有本机库与文件做了完整备份，在独立 PostgreSQL 与文件目录中恢复 7 个项目、13 项素材和 120 个文件。哈希一致，恢复后素材 Range 请求返回 206。 [恢复演练](guardian-recovery.json)
- 本机 Guardian 页面及生产构建返回 HTTP 200，API、数据库和 1 个 Worker 就绪，付费开关关闭。 [本机运行验证](guardian-readiness.json)

|故意注入的问题|实际处理|
|---|---|
|主角外观变化、服装颜色改变、背景错误、画面缺主角|制作真实错误候选并抽帧，记录身份、服装、场景、镜头不符四类退回。四条采纳请求均返回 409。|
|服装键不存在、未批准场景、换手拿道具、动作无法衔接、与正史矛盾|规则返回问题类别和镜头位置，阻止批准。浏览器能定位固定分镜，看见预期与实际登记值。|
|错误音色|配音任务入队前返回 422。正确音色实际生成语音及一条对白字幕。|
|候选媒体按原长度损坏|重新计算哈希后拒绝采纳。修复测试文件后，原审核仍可追溯。|
|角色版本变更、旧任务提交|未更新固定引用的草稿阻止批准。角色新版本与分镜重新绑定并获批后，旧的排队候选不能审核或采纳，已采纳的历史文件仍可核对哈希。 [换版专项](guardian-identity-tests.xml)|

## 文件范围

- 后端 `backend/app/{guardian,story_schemas,creative,series,generation,voice,timeline,production,delivery}.py` 与 `backend/tests/test_guardian.py`。
- 前端故事圣经、角色与分镜、候选、配音使用现有工作区。新增 `frontend/src/pages/GuardianPage.vue` 及 `frontend/src/components/production/Guardian{Rules,Shot}.vue`，并扩展相应页面与路由。
- 验收 `scripts/browser-v3-guardian.mjs`、`scripts/isolated_regression.py`，以及本记录、真实截图、JUnit 和交付证据。

## 复验与回滚

```powershell
Push-Location frontend
try {
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
} finally { Pop-Location }
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --v3-browsers --junitxml data/tmp/guardian-backend.xml --browser-evidence data/tmp/guardian
```

数据库仍为 `0013`。已经创建 Guardian 合同的项目应先归档创作、素材和数据库。旧版本程序只识别原有制作入口，不能继续为启用 Guardian 的项目执行质量关卡。可先在独立数据库和存储目录恢复升级前的备份，确认后再切换本机服务。启用前可直接回滚代码。

```powershell
$release = git log -1 --format=%H --grep='^Enforce Guardian shot contracts and review approved candidates$'
if (-not $release -or (git status --porcelain --untracked-files=no)) { throw 'Track or preserve other changes before rollback.' }
& ./scripts/stop.ps1
git revert --no-edit $release
if ($LASTEXITCODE -ne 0) { throw 'Resolve revert before restarting.' }
Push-Location frontend
try {
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
} finally { Pop-Location }
& ./scripts/start.ps1 -Production
```
