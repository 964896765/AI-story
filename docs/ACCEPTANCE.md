# 阶段验收记录（2026-10-27，Asia/Shanghai）

## 状态

P8 本地运镜、候选预览和人工采纳见 [P8 验收](P8_ACCEPTANCE.md)。真实 AI 生成与远程算力待接入。

P7 故事圣经与三集本地计划见 [P7 验收](P7_ACCEPTANCE.md)。生成式分镜与视觉一致性仍待验。

P6 本地解析、审核快照与创作链见 [P6 验收](P6_ACCEPTANCE.md)。媒体分析迁移增加 0007；真实感知模型待接入。

P0 初始化完成；P1 业务基础按本记录范围通过自动化与真实 HTTP 验收。以下为 P1 历史记录；本轮 P2 实施、测试和回滚见 [P2_ACCEPTANCE.md](P2_ACCEPTANCE.md)，下文的未完成项以 P1 当时状态为准。

P3批量可靠性验收见 [P3_ACCEPTANCE.md](P3_ACCEPTANCE.md)，当时数据库为0004。历史未完成项以各阶段记录为准。

P4创作资产基础历史验收见 [P4_ACCEPTANCE.md](P4_ACCEPTANCE.md)，当时数据库0005。

P5-A/B文本治理与模拟剧情工作流见 [P5_ACCEPTANCE.md](P5_ACCEPTANCE.md)，当前数据库0006。真实API未授权、预算0，真实AI质量验收未执行；图片、视频、TTS模型未接入。

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
