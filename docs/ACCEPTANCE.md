# 阶段验收记录

2026-11-19 本机 V2.0 最终发布检查通过 121 项后端测试及 11 条生产构建浏览器流程。0013、回环前端、Worker 与本机简体中文 OCR 就绪，真实模型预算为 0。 [发布证据](v2-release-acceptance.json) · [后端回归](v2-release-backend-tests.xml)

## 状态

全站 Web UI 已按 PRISM STUDIO HTML 原型更新。12 个主工作区、旧业务链接、全站主题及移动布局已验证。 [工作台验收、截图与回滚](V3_PRISM_WEB_UI_ACCEPTANCE.md)

Production Guardian 本机链路支持正史与镜头合同批准、连续性校验、候选证据与人工审核、局部返工和授权交付。真实视觉模型仍待接入。 [使用、验收和回滚](V3_GUARDIAN_ACCEPTANCE.md)

V3 第十批交付整剧审片监看、响度与字幕质检、复用成片复检及报告下载。后端 137 项、Chrome 14 条流程、6 集真实生产负载和独立备份恢复通过。 [验收、截图与回滚](V3_10_QUALITY_ACCEPTANCE.md)

V3 第九批交付长音频分段、接缝定位、Worker 续跑与统一 SRT。后端 133 项、生产构建 Chrome 14 条流程通过，另验证 30 分钟转写上限。 [验收、截图与回滚](V3_09_LONG_ASR_ACCEPTANCE.md)

V3 第八批交付 Windows 本机语音转写、指定音轨试听与定位、SRT 校对及成片烧录。后端 130 项、生产构建 Chrome 13 条流程通过。 [验收、截图与回滚](V3_08_LOCAL_ASR_ACCEPTANCE.md)

V3 第七批交付字幕历史版续改、播放预览和本机草稿恢复。后端 128 项、生产构建 Chrome 12 条流程通过，另存新版后旧成片与原字幕哈希仍一致。 [验收、截图与回滚](V3_07_SUBTITLE_DRAFT_ACCEPTANCE.md)

V3 第六批交付本机硬字幕时序估算、采样画面对照、SRT 校对和剪辑。后端 128 项、生产构建 Chrome 12 条流程通过。 [验收、截图与回滚](V3_06_HARD_SUBTITLE_ACCEPTANCE.md)

V3 第五批交付软字幕校对、不可变 SRT 素材版本及成片烧录。后端 125 项、生产构建 Chrome 12 条流程通过。 [验收、截图与回滚](V3_05_SUBTITLE_ACCEPTANCE.md)

V3 第四批交付分集待办、问题点预览、固定批次返工、授权预检及人工发行交接。后端 124 项、生产构建 Chrome 12 条流程及独立恢复通过。 [验收、截图与回滚](V3_04_HANDOFF_ACCEPTANCE.md)

V3 工作台前端改版覆盖总览、素材、创作、剪辑、生产和质检。独立回归 124 项后端测试与 12 条生产构建浏览器流程通过。 [改版、截图与回滚](V3_03_WORKBENCH_ACCEPTANCE.md)

V3 第二阶段首批交付覆盖智能解析工作台的审片、选轨和固定位置链接。后端 123 项、生产构建 Chrome 12 条流程通过。 [验收与回滚](V3_02_ANALYSIS_ACCEPTANCE.md)

P11 黑场质检定位、片段修正、返回原批次和重新渲染见 [片段返工验收](P11_CLIP_REWORK_ACCEPTANCE.md)。

P10 同轨拖动、双边裁剪、吸附、键盘操作及新版本渲染见 [直接编辑验收](P10_FRAME_EDIT_ACCEPTANCE.md)。

P6-B 简体中文画面文字识别、镜头对齐和人工校对采纳见 [本机 OCR 验收](P6B_OCR_ACCEPTANCE.md)。

P14 本机 V2.0 发布检查、系统诊断、三集 30 秒交付实测及 0013 完整恢复见 [P14 验收](P14_ACCEPTANCE.md)。各工作区的通过范围与待办见 [能力矩阵](CAPABILITY_MATRIX.md)。真实模型预算为 0，发行操作仍由用户在授权平台完成。

P13 渠道、发行登记、推广与结算见 [P13 验收](P13_ACCEPTANCE.md)。实际平台发布未接入。

P12 作品、素材授权、整剧 ZIP 交付见 [P12 验收](P12_ACCEPTANCE.md)。

P11 整剧队列、技术质检、分集返工见 [P11 验收](P11_ACCEPTANCE.md)。

P10 本地多轨、自动装配和三集真实渲染见 [P10 验收](P10_ACCEPTANCE.md)。

P9 双角色本机配音与字幕见 [P9 验收](P9_ACCEPTANCE.md)。音源分离和云端 TTS 待接入。

P8 本地运镜、候选预览和人工采纳见 [P8 验收](P8_ACCEPTANCE.md)。真实 AI 生成与远程算力待接入。

P7 故事圣经与三集本地计划见 [P7 验收](P7_ACCEPTANCE.md)。生成式分镜与视觉一致性仍待验。

P6 本地解析、审核快照与创作链见 [P6 验收](P6_ACCEPTANCE.md)。媒体分析迁移增加 0007；真实感知模型待接入。

P0 初始化完成；P1 业务基础按本记录范围通过自动化与真实 HTTP 验收。以下为 P1 历史记录；本轮 P2 实施、测试和回滚见 [P2_ACCEPTANCE.md](P2_ACCEPTANCE.md)，下文的未完成项以 P1 当时状态为准。

P3批量可靠性验收见 [P3_ACCEPTANCE.md](P3_ACCEPTANCE.md)，当时数据库为0004。历史未完成项以各阶段记录为准。

P4创作资产基础历史验收见 [P4_ACCEPTANCE.md](P4_ACCEPTANCE.md)，当时数据库0005。

P5-A/B 文本治理与模拟剧情工作流见 [P5 验收](P5_ACCEPTANCE.md)，当时数据库 0006。真实文本模型质量仍待授权验收。P9 已验收 Windows 本机配音。

## P0 实际交付

- 新建 Git 仓库、独立虚拟环境；未修改其他项目、全局 Python/Node 配置或已有服务。
- Vue 3 / TypeScript / Vite 前端、FastAPI / SQLAlchemy / Psycopg 后端。
- PostgreSQL Compose 只绑定 127.0.0.1；启动 Docker Desktop 后发现已有 postgres:16-alpine，停止额外镜像拉取并复用已有镜像。项目独立网络、数据卷与容器，不复用其他项目数据库。
- `.env` 随机生成数据库密码，Git 已忽略；前端不含数据库凭据或模型密钥。
- 8000 已占用，未终止原服务；本项目改用后端 18000、前端 15173。
- 没有下载 AI 权重、调用付费 API 或部署公网。

## P1 实际交付

|能力|真实实现与证据|
|---|---|
|项目|名称、长说明、预算字段创建与数据库列表；UI 对接 API|
|素材|流式批量上传、授权记录、SHA-256、大小、独立存储、版本初始值；原始素材不被解析覆盖|
|媒体|ffprobe 独立子进程；限制协议/封装格式，60 秒超时；真实音视频信息回写数据库|
|任务|queued/running/succeeded/failed；数据库行锁领取、项目内幂等键、失败手动重试、120 秒租约过期恢复、尝试次数与追加事件|
|前端|6 个工作区，项目与素材、视频预览、真实任务状态与错误、日志、已入账费用查询；未实现功能明确标注|
|迁移|0001 固定 PostgreSQL DDL；实际 upgrade、测试库 downgrade/upgrade、alembic check 均通过|
|健康与安全|数据库/迁移/ffmpeg/ffprobe 就绪检查；Host/Origin/本机来源限制、路径边界检查、独立 UUID 文件名、源文件独占创建|

## 实际测试结果

1. Python 自动化最终运行：**7 passed**，无跳过。PostgreSQL 独立测试库 story_test，不使用 SQLite。覆盖真实音视频解析、非法文件失败、路径越界、上传校验与防覆盖、请求来源、输入校验、真实上传入库、并发幂等、并发领取、成功任务拒绝重试、失败重试、事件记录和过期租约。
2. 1 条上游弃用提示：Starlette TestClient 对 httpx 适配将来需迁移到 httpx2；当前断言全部通过，未屏蔽提示。
3. 前端 `npm run build`：vue-tsc 类型检查与 Vite 生产构建通过。
4. 真实 HTTP：Vite 页面 200 → 代理健康检查 ready=true → 创建项目 → 上传自行生成的 2 秒视频 → 入队 → 独立 Worker 完成，attempt=1 → 预览 Range 返回 206。留有明确命名的“P1 真实视频验收”项目和测试素材，不冒充生产内容。
5. PostgreSQL 正式数据库迁移到 0001；独立测试数据库可降级/升级，模型比对无差异。测试库目前保持已迁移空表结构。
6. npm 官方审计最终 0 项已知漏洞；Python 运行与测试依赖锁清单审计 0 项已知漏洞。初选依赖已升级，完整虚拟环境审计曾发现扫描工具自身 filelock 漏洞；其修复版要求 Python 3.11，已卸载 pip-audit、CacheControl、filelock，不强改系统 Python。`pip check` 无依赖冲突。漏洞扫描不等同于完整安全或许可证审查。

证据：`backend-tests.xml`、`http-acceptance.json`、`frontend-audit.json`、`python-runtime-audit.json`；`python-audit-before-cleanup.json` 保存审计工具移除前的历史结果。

## 未完成与边界

- 没有完整剪辑、字幕烧录、音轨处理和成片导出；解析视频不等于生产流水线完成。
- 预算字段与费用账本已建，但没有付费调用、预算预留/拦截、模型适配器执行与对账。
- Worker 仅支持 probe；租约到期标记失败并手动重试，不支持所有未来步骤自动恢复。无全局并发限额、任务取消、暂停或精确百分比。
- 无项目编辑/归档、素材删除、分页、磁盘配额、上传断点续传、资产版本链、角色/场景/剧本系统。
- 无自动备份、恢复演练、自动质检、运营数据导入或平台发布。
- 当前本机可信用户模式，无账户与权限隔离，不适用于公网或局域网多用户环境。
- 许可证已做直接依赖初筛；完整传递依赖、容器组件与编码专利审核留待商用分发前处理。

## 修改文件清单

- 根配置：`.gitignore`、`.env.example`、`compose.yaml`、`README.md`。
- 后端：`backend/requirements.txt`、`requirements.lock`、`alembic.ini`；`app/__init__.py`、`config.py`、`db.py`、`models.py`、`storage.py`、`media.py`、`main.py`、`worker.py`；`migrations/env.py`、`migrations/versions/0001_foundation.py`；`tests/test_core.py`、`tests/test_postgres.py`。
- 前端：`frontend/package.json`、`package-lock.json`、`index.html`、`tsconfig.json`、`vite.config.ts`、`src/main.ts`、`src/App.vue`、`src/style.css`。
- 脚本：`scripts/start.ps1`、`scripts/check.ps1`、`scripts/integration.py`。
- 文档：本文件、`ARCHITECTURE.md`、`LICENSE_REVIEW.md` 及上述测试证据。
- `.env`、`.venv`、`data`、node_modules 和 dist 为忽略的本地配置/运行产物，未提交凭据与视频。

## 回滚

1. 按 `data/runtime/processes.json` 核实本项目的 API、Worker、Vite 进程及命令行后停止。不要按端口批量杀进程。
2. 停止写入后备份 PostgreSQL 与整个 data 目录，再停止本项目数据库：根目录 `docker compose stop db`。此操作保留卷，禁止用 `down -v` 清理业务数据。
3. 本轮为全新工程，没有旧版本业务需要还原；代码保留为 Git 初始基线。后续回滚只回退本工程版本，不覆盖原始素材。
4. `alembic downgrade base` 会删除全部业务表，**仅允许对可丢弃测试库执行**；生产库优先从备份恢复，不用降级清空回滚。
