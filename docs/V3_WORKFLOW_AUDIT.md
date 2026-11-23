# 刀码漫剧 V3 六阶段功能审计

审计基线为 GitHub `master` 的 `5e99d685c39b19177fae8891dcc16018e875c839`。六阶段和 24 步以 [现有工作流定义](../frontend/src/router/workflow.ts) 为准。功能状态描述软件当前能力，项目进度仍由项目记录、审批和真实任务决定。

审计后的增量已覆盖 01.2 的项目规格持久化与版本锁定，以及 01.4 的两条本机 Agent 工作流和固定版本交接。下表保留审计时的基线记录。 [V3.11 制作规格](V3_11_PRODUCTION_SPECS_ACCEPTANCE.md) · [V3.12 Agent 执行治理](V3_12_AGENT_RUNS_ACCEPTANCE.md)

05.1 在 V3.13 进入部分实现。固定人物、场景或批准镜头可创建候选，离线运行已贯通审核与入库，真实供应商验收待授权。 [V3.13 图片候选](V3_13_IMAGE_CANDIDATES_ACCEPTANCE.md)

**本机可执行**表示有可操作的本机链路。**人工／规则**表示依赖人工、规则或两者。**模拟已验收**用于已复验的模拟链路。**部分实现**表示部分业务可执行，目标链路仍缺关键环节。**待接入**表示该步的目标执行能力还未接上。

## 24 步功能状态

|编号与步骤|状态|当前入口与实际产出|缺口与验收依据|
|---|---|---|---|
|01.1 创建项目与授权登记|本机可执行|项目与素材保存说明、原件、来源及素材级授权版本；交付按平台、地域、时效和商用范围核验。|项目说明是自由文本，正式授权以素材权利记录为准。 [项目接口](../backend/app/main.py) · [授权接口](../backend/app/library.py) · [P12](P12_ACCEPTANCE.md)|
|01.2 确定制作规格|部分实现|向导把集数、单集时长、画风和画幅写入当前浏览器的备注。各生产模块各自保存参数。|暂无进入导演与审批的统一结构化项目规格。 [向导](../frontend/src/pages/WizardPage.vue) · [模型与流程验收](V3_MODEL_WORKFLOW_ACCEPTANCE.md)|
|01.3 配置模型与预算|部分实现|兼容文本适配器有配置、报价、预算预留和账本。Codex 与媒体配置可保存草稿，CLI 探测只返回发现状态。|现有真实调用关闭、预算 0 元。Codex 运行、媒体适配和真实费用待接入或验证。 [接入配置](../backend/app/model_connections.py) · [模型治理](P5_MODEL_CONTRACT.md)|
|01.4 制定执行计划|部分实现|导演表单按选定模式整理要求和交接。固定时间轴、整剧批次与交付可持久化并经人工批准执行；离线模型建议可比较待批方案。|从原稿自动拆解的全剧计划、跨 Agent 分派与交接尚缺。 [导演接口](../backend/app/director.py) · [整剧批次](V3_DIRECTOR_BATCH_ACCEPTANCE.md) · [规划模拟](V3_DIRECTOR_ADVICE_ACCEPTANCE.md)|
|02.1 保存原稿|本机可执行|小说与剧本可保存内容和来源；追加版本，支持历史、对比和恢复。|创意宜存入正式小说或剧本版本供下游引用。 [创作接口](../backend/app/creative.py) · [P4](P4_ACCEPTANCE.md)|
|02.2 剧情解析与改编|模拟已验收|从固定原稿生成结构化模拟草稿；可编辑、比较、拒绝或人工采纳后追加正式剧本版本。|兼容 HTTP 适配已有，真实中文剧情质量与账单未验收；规则整理保留原文。 [文本接口](../backend/app/text_routes.py) · [P5](P5_ACCEPTANCE.md)|
|02.3 全剧大纲与分集|人工／规则|可手工编辑分集；规则工具按段落和字数拆分，持久化分集并引用原剧本。|缺少经真实模型验收的情节级大纲与分集。 [规则拆分](../backend/app/creative.py) · [P4](P4_ACCEPTANCE.md)|
|02.4 分集剧本与审核|部分实现|可保存分集、正文及版本；模型改编稿可以审核采纳，故事圣经后续固定选定版本。|尚无独立的逐集剧本签审门禁与自动连贯审稿。 [剧本与分集结构](../backend/app/story_schemas.py) · [P5](P5_ACCEPTANCE.md)|
|03.1 建立故事圣经|本机可执行|手工编制故事圣经，固定剧本、分集与分镜；Guardian 可登记正史事实和风格约束。|用于最终审批的计划需补齐分镜引用。 [系列计划](../backend/app/series.py) · [Guardian](V3_GUARDIAN_ACCEPTANCE.md)|
|03.2 人物定妆与声音|部分实现|角色版本可固定身份、服装、授权参考图及本机音色；可沿用已批准的参考图。|缺少自动定妆、多角度角色图和声纹核验。 [角色结构](../backend/app/story_schemas.py) · [参考图](V3_GUARDIAN_REFERENCE_ACCEPTANCE.md)|
|03.3 场景、道具与美术|人工／规则|保存场景与参考图，在故事圣经登记道具和美术风格；分镜填写持有状态。|主要由用户登记和核对，尚无美术生成作业或独立道具制作链。 [固定约束](../backend/app/guardian.py) · [Guardian](V3_GUARDIAN_ACCEPTANCE.md)|
|03.4 核对固定版本|本机可执行|创作引用锁定指定版本，镜头合同保存哈希，换版可查看影响并复用未变镜头。|启用 Guardian 后才执行对应合同约束。 [版本与影响](../backend/app/series.py) · [单镜返工](V3_GUARDIAN_SHOT_REWORK_ACCEPTANCE.md)|
|04.1 编写分镜|人工／规则|分镜工作台编辑镜头 ID、时长、人物、场景和首尾状态；规则可生成初稿。|规则拆分没有自动分镜导演能力；镜头内容仍需人工补齐。 [分镜结构](../backend/app/story_schemas.py) · [P7](P7_ACCEPTANCE.md)|
|04.2 检查动作与空间衔接|人工／规则|规则核验已填写的首尾状态、道具、剧情事实及跨集衔接，给出阻断和复核项。|执行依据是结构化记录；真实像素中的动作、位置和拿物情况由人工审看片段。 [规则实现](../backend/app/guardian.py) · [规则与错误样本](V3_GUARDIAN_ACCEPTANCE.md)|
|04.3 选择模型与输入规格|部分实现|可保存固定来源的模型输入计划、镜头合同和供应商配置。文本报价走既有模型治理。|媒体模型输入契约、动态能力、价格及排程尚未贯通。 [输入计划](../backend/app/story_schemas.py) · [配置与预算](V3_MODEL_WORKFLOW_ACCEPTANCE.md)|
|04.4 批准镜头与制作计划|本机可执行|审批重验连续性与版本后追加批准版。Guardian 生成核验输入、镜头合同时长及有效批准版本。|审批适用于已实现的本机生产链。 [审批](../backend/app/series.py) · [候选入口](../backend/app/generation.py) · [Guardian](V3_GUARDIAN_ACCEPTANCE.md)|
|05.1 图片与关键帧|待接入|可导入有权图片作为参考、定妆或关键帧，保存接入草稿。|无外部生图执行、远端状态、结果回收与成本验收。 [生成能力接口](../backend/app/generation.py) · [模型目录](MODEL_CATALOG.md)|
|05.2 审核候选一致性|人工／规则|审核员可预览、A/B 对比、查固定参考并选择证据帧；规则可检测部分技术及屏幕文字问题。|身份、服装、道具、实际场景仍需人工。技术检查和人工退回记录可追溯。 [逐项审核](V3_GUARDIAN_CHECKLIST_ACCEPTANCE.md) · [OCR](V3_GUARDIAN_OCR_ACCEPTANCE.md)|
|05.3 AI 动态视频|待接入|FFmpeg Worker 可用已有静图创建片段，支持固定镜头、候选预览和人工采纳。|万相、海螺、Seedance、可灵仅有配置入口，暂无远端执行。 [候选实现](../backend/app/generation.py) · [P8](P8_ACCEPTANCE.md)|
|05.4 配音与字幕|本机可执行|用已安装的 Windows 音色生成多角色对白和 SRT/VTT，支持试听与采纳。|云端 TTS、语义级对白理解、声纹和音源分离未打通。 [配音](../backend/app/voice.py) · [P9](P9_ACCEPTANCE.md)|
|06.1 镜头质检与汇合|人工／规则|候选解码、抽帧、黑画面与低变化检查，配合合同审核和人工采纳；可替换局部镜头。|视觉语义、自动判定新角色外观仍待接入；已固定镜头才进入 Guardian 后期流程。 [视觉检查](V3_GUARDIAN_VISUAL_ACCEPTANCE.md) · [局部返工](V3_GUARDIAN_SHOT_REWORK_ACCEPTANCE.md)|
|06.2 多轨剪辑与合成|本机可执行|时间轴可编辑视频、对白、配乐和字幕。自动装配要求指定分集每镜有唯一合格候选；附加轨道可继续编排。|还未实现从语义素材自动编完整时间轴及自动消歧。 [装配接口](../backend/app/timeline.py) · [P10 多轨](P10_ACCEPTANCE.md) · [配乐压低](V3_MUSIC_DUCKING_ACCEPTANCE.md)|
|06.3 渲染与成片复检|本机可执行|按集后台渲染和技术质检，检查黑场、冻结、响度、字幕与固定对白；可按集返工或重用既有产物。|真实商业长剧的并发、质量及运营成本待验。当前全局一次领取一个任务。 [生产接口](../backend/app/production.py) · [质检实现](../backend/app/quality.py) · [整剧实测](V3_10_QUALITY_ACCEPTANCE.md)|
|06.4 终审、交付与归档|本机可执行|通过质检与授权后打包 MP4、封面、固定版本、适用字幕和证据，ZIP 可验证哈希；发行及结算靠人工记录。|无平台自动发布。新 Guardian 包带审核 JPEG。 [授权交付](../backend/app/delivery.py) · [证据包](V3_GUARDIAN_DELIVERY_EVIDENCE_ACCEPTANCE.md) · [运营记录](P13_ACCEPTANCE.md)|

合计 9 步本机可执行、6 步人工／规则、1 步模拟已验收、6 步部分实现、2 步待接入。

## 横向核对与实施顺序

- **版本和任务**。FastAPI、PostgreSQL、Worker 和本机文件构成业务事实源；版本追加和固定引用、审批与任务入队、任务租约、FFmpeg 出件校验，以及授权 ZIP 均有相应后端入口。当前 Worker 领取使用 PostgreSQL 全局锁，不具备生产级多 Worker 并发。媒体解析已有探测、分轨、抽帧、字幕、波形、本机 OCR 与 ASR。说话人分段、音源分离和视频语义理解仍缺适配。 [Worker](../backend/app/worker.py) · [解析设计](ARCHITECTURE.md) · [解析能力](../backend/app/perception.py)
- **资金与故障**。文本链路实现原子预留、用量结算、未知状态保留及手工对账。CLI 检测、媒体供应商草稿和文本模拟分别反映各自实际状态，不能推导出已认证、已生成图像或视频、已核实价格。后续媒体调用须补适配器、报价、提交回执和安全重试，再安排真实验收。 [文本契约](P5_MODEL_CONTRACT.md) · [模型目录](MODEL_CATALOG.md)
- **项目导航**。向导的“建议下一步”依据项目统计和最近任务。项目中的任意时间轴、已采纳独立候选或旧批次可能被选为提示依据。这是导航提示，生产仍按各 API 校验固定输入。后续可把推荐绑定到当前批准计划、分集、候选合同和审核待办。 [项目汇总](../backend/app/overview.py) · [导航规则](../frontend/src/router/workflow.ts)
- **后续增量**。先完善共享制作规格、Agent 受限业务契约以及固定版本交接。分别建设 Codex 工程维护执行和内容创作 Agent 的权限与记录。图片、视频先分开实现模拟网络合同、审批、额度、状态恢复和候选落盘，逐供应商在获授权后验收。最后推进视觉语义、镜头级资源调度与多 Worker。现有本机主链用于每批回归。

## 本轮增量与复验

在现有流程定义上增加能力状态，向导显示五类状态和实际入口。“待接入”的图片和动态视频步骤仍可进入本机运镜工作区。保留六阶段和 24 步的顺序与名称。此次变化涉及 `workflow.ts`、`WizardPage.vue`、浏览器回归及验收文档。数据库仍为 `0016`。

- 逐项比对文档与源码的 24 个标题、编号和状态，检查相对链接有效。空库迁移、Alembic 检查、后端 166 项测试、Vue 类型检查和 Vite 生产构建通过。保留一条 Starlette/httpx 上游弃用提示。
- Chrome 从首阶段逐步读取全部 24 个状态。确认两个待接入的步骤只进入本机候选页，生成阶段在 390px 宽度无横向溢出。浏览器运行使用独立数据和真实 FFmpeg 样片。 [截图](v3-workflow-audit.png)
- 两集十镜 Guardian 复验通过。四类画面异常按审核记录阻止采纳。返工一镜、复用九镜，最终 ZIP 的 30 张 JPEG 审核证据通过哈希核对。证据缺失、等长篡改及恢复后重试均复验，外部调用为 0。 [Chrome 记录](v3-workflow-audit-browser.json)
- 实际本机向导返回 200 并加载本轮前端构建；1 个 Worker 在线、并发上限为 1，Codex CLI 可发现，外部执行关闭，真实文本默认额度为 0。

```powershell
npm.cmd --prefix frontend run build
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --junitxml data/tmp/v3-workflow-audit-backend.xml
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-01 --browser-evidence data/tmp/v3-workflow-audit
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --browser-phase v3-guardian --browser-evidence data/tmp/v3-workflow-audit-guardian
```

回滚可对本次提交执行 `git revert` 后重建前端。使用当前 PostgreSQL `0016`，无需迁移或恢复生产数据。
