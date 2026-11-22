# 版本变更

## PRISM STUDIO 全站 Web UI

- 使用 HTML 原型的 12 项侧栏、项目总览、全局深浅主题、AI 总导演与六步向导。
- 角色、分镜、生成、配音、多轨剪辑、生产调度及质量控制采用对应工作台布局。 [浏览器验收](docs/V3_PRISM_WEB_UI_ACCEPTANCE.md)

## V3 第十批 · 整剧质检与增量复检

- 整剧生产页可并排查看分集问题与成片，保存人工复核并下载质检报告。
- 技术质检测量响度和真峰值，核验画面规格与字幕文件。只修改规则时可复用已经校验的成片。 [验收记录](docs/V3_10_QUALITY_ACCEPTANCE.md)

## 3.0.0 · 前端第一阶段 · 2026-11-20

- 使用 Vue Router、Pinia、Lucide Vue 和 Naive UI 重整应用外壳及 12 个一级入口，保留已有工作区。
- 项目总览从业务记录读取素材、制作阶段、任务、费用、待审和成片。固定素材、草稿、时间轴与批次支持路由链接。
- 新增只读项目总览 API，数据库沿用 0013。 [审计与验收](docs/V3_01_ACCEPTANCE.md)

## 2.0.0 · 2026-11-19

- 回归已有项目、素材、剪辑、任务和创作版本。P5 新增模型预算、离线改编审核与账单登记。 [阶段验收](docs/ACCEPTANCE.md)
- 新增本机解析、证据审核、故事圣经、跨集分镜、本地运镜和 Windows 系统配音。 [能力矩阵](docs/CAPABILITY_MATRIX.md)
- 新增多轨自动装配、整剧生产、技术质检、分集返工、权利与整剧交付、人工发行和结算导入。 [阶段验收](docs/ACCEPTANCE.md)
- 新增运行诊断及本机发布检查。PostgreSQL 迁移到 0013，生产样本和备份独立恢复通过。 [P14 验收](docs/P14_ACCEPTANCE.md)
- 补齐 Windows 本机画面文字识别，支持采样回查、镜头对齐、人工校对和剧本采纳。 [P6-B OCR 验收](docs/P6B_OCR_ACCEPTANCE.md)
- 补齐多轨时间轴的拖动、裁剪、吸附和键盘逐帧编辑。 [P10 直接编辑验收](docs/P10_FRAME_EDIT_ACCEPTANCE.md)
- 支持从质检证据定位固定片段，修正后返回原批次并复检。 [P11 片段返工验收](docs/P11_CLIP_REWORK_ACCEPTANCE.md)
