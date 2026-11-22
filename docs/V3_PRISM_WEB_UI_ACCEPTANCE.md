# PRISM STUDIO 全站 Web UI

根据用户提供的 `AI_Story_V3_PRISM_STUDIO_Web_UI_交互概念原型.html` 改造现有 Vue 应用。HTML SHA-256 为 `453fab0460bb17bb5effc1b5eed7d8982fb22fd2951630ee3164881955fd02a2`。首页使用原型的渐变制作横幅、四项指标和三栏布局，项目名、进度、审核、费用、封面和成片取自现有 API。旧主导航由原型的 12 个入口替换。

|区块|主工作区|业务入口|
|---|---|---|
|Workspace|项目总览 · AI 总导演 · 创作向导|打开实际待办和生产批次，保存本地执行计划，按六步打开工作区|
|Create|小说与剧本 · 角色与场景 · 分镜工作台|原稿编辑和改编审核，素材库和智能解析，镜头序列、故事圣经及固定版本检查|
|Production|AI 图片与视频 · 配音与声音 · 剪辑与时间轴|真实候选 A/B 预览、证据审核、本机音色与字幕、素材浏览、轨道和片段属性|
|Manage|生产调度 · 质检与交付 · 模型与设置|队列与 Worker，Guardian、成片、授权 ZIP、运营，供应商预算和系统诊断|

## 验收范围

- 依据原型切换全局浅色和深色主题。桌面在 1280 像素采用图标侧栏，移动端使用可收合抽屉。检查 390、1280、1440、1920 像素视口及移动端五个业务页面。 [浅色总览](prism-overview.png) · [深色主题](prism-dark.png) · [手机界面](prism-mobile.png)
- AI 总导演按用户选定工作流生成本地计划，保存制作指令与交接确认。创作向导读取项目记录，保存每阶段备注并打开实际操作。 [AI 总导演](prism-director.png) · [创作向导](prism-wizard.png)
- 剪辑工作台有素材浏览器、视频监看、多轨与片段属性。已有素材版本、历史链接、播放、渲染、审核、任务取消与恢复使用原业务实现。 [剪辑工作台](prism-timeline.png) · [Guardian 审核](prism-guardian.png)
- 生成中心专项验证了两个真实本机候选的 A/B 双播放器、键盘采纳和下游剪辑引用。 [A/B 对比截图](prism-generation.png) · [验收记录](prism-generation.json)
- 已安装 Chrome 验证 15 条端到端流程，包含完整 Guardian 十镜头交付。另跑通六集真实视频生产及成片复检负载。Vue 类型检查、Vite 生产构建和 138 项后端测试通过。数据库为 `0013`，测试在独立库进行。 [页面交互](prism-browser.json) · [后端 JUnit](prism-backend-tests.xml) · [负载回归](prism-load.json)
- 本机首页、总导演、剪辑工作台及新版入口脚本返回 HTTP 200，Worker 在线。 [本机就绪记录](prism-readiness.json)
- AI 总导演当前负责本地计划与人工交接，语义模型驱动的自动执行、语义视觉模型及付费生成仍待接入。测试实际外部支出为 0。

## 启动与复验

```powershell
Push-Location frontend
try {
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
} finally { Pop-Location }
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --v3-browsers --junitxml data/tmp/prism-backend.xml --browser-evidence data/tmp/prism
# 本机尚未启动时运行
& ./scripts/start.ps1 -Production
```

## 回滚

以下反向提交撤回本次 Vue、样式与浏览器测试改动。已运行的 Vite 预览会读取重新构建的 `dist`，浏览器刷新后载入回滚版本。数据库继续使用 `0013`。

```powershell
$release = git log -1 --format=%H --grep='^Replace the workbench with the PRISM Studio web interface$'
if (-not $release -or (git status --porcelain --untracked-files=no)) { throw 'Preserve other tracked changes before rolling back.' }
git revert --no-edit $release
if ($LASTEXITCODE -ne 0) { throw 'Resolve the revert before building.' }
Push-Location frontend
try {
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
} finally { Pop-Location }
```
