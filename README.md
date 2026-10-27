# AI 漫剧工厂

面向 Windows 的本机生产工作台。独立编写，未复制第三方漫剧项目源码。当前实现 P1 基础与媒体解析任务；完整视频剪辑流水线和云端 AI 尚未实现。验收状态见 [阶段记录](docs/ACCEPTANCE.md)。

## 本地启动

现有工具要求：Python 3.10+、Node 20.19+、Docker Desktop Linux Engine、FFmpeg/ffprobe（PATH 可调用）。服务仅绑定 127.0.0.1，不部署公网。

1. 在根目录复制 `.env.example` 为 `.env`，设置强随机 PostgreSQL 密码，同时更新 `DATABASE_URL` 中的密码（URL 保留字符须百分号编码）。不要提交 `.env`。
2. 启动 Docker Desktop，确认 `docker info` 成功。
3. 根目录执行 `docker compose up -d db`。首次运行会下载 PostgreSQL 16 镜像，不会下载 AI 模型。
4. 根目录执行 `python -m venv .venv`，然后 `.\.venv\Scripts\python -m pip install -r backend/requirements.lock`。
5. 在 `backend` 目录执行 `..\.venv\Scripts\alembic upgrade head`。
6. 在 `backend` 目录分别开两个终端运行：
   - `..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 18000`
   - `..\.venv\Scripts\python -m app.worker`
7. 在 `frontend` 目录执行 `npm ci` 和 `npm run dev`，打开 http://127.0.0.1:15173 。

进入素材资产中心，新建项目，填写授权来源，批量导入视频。点击“读取媒体信息”，在批量生产页查看真实任务、错误与日志。播放受浏览器编码支持限制。

API 文档：http://127.0.0.1:18000/docs 。健康检查 `/api/health` 在数据库、迁移或工具未就绪时返回 503。前端遇到错误显示实际错误，不注入演示数据。

## 验证

在 backend 目录运行 `..\.venv\Scripts\python -m pytest -q`。包含 FFmpeg 自行生成的一秒测试视频，不使用未授权素材。

PostgreSQL 集成测试需独立测试数据库，先以其 `DATABASE_URL` 执行迁移，再设置 `TEST_DATABASE_URL` 指向同一测试库后运行 pytest。不要对生产库运行集成测试。未配置时测试明确跳过，不代表通过。

也可在根目录设置好 `TEST_DATABASE_URL` 后运行 `.\.venv\Scripts\python scripts/integration.py`，脚本仅对指定测试库迁移并执行测试。

前端：`npm run build` 同时执行 Vue/TypeScript 类型检查。

## 数据、安全与恢复

- PostgreSQL 保存项目、素材、任务、事件与费用；视频保存在 `data/originals`，UUID 命名，不采用上传者提供的磁盘路径。API 无任意路径导入接口。
- 上传单文件最大 2 GiB，流式复制并计算 SHA-256。重复哈希可识别同内容，但目前不自动去重。文件与数据库无法组成原子事务，异常退出可能留下孤立文件；备份和清理前须对照资产表，禁止直接删除原始素材。
- Worker 使用 `FOR UPDATE SKIP LOCKED` 领取任务；每个进程一次处理一个任务。解析超时 60 秒、租约 120 秒。过期任务在 Worker 下一轮扫描时标记失败，用户可手动重试。尚无全局并发上限与 Worker 心跳面板。
- 幂等键在项目内唯一，同键不同素材返回冲突；重试保留任务 ID、递增尝试次数并追加日志。当前仅无付费副作用的 probe 任务。
- 浏览器每 3 秒查询真实任务状态，不显示虚构百分比。没有模型费用记录时显示已入账费用为零，明确不含机器、电力等成本。
- 无用户账号系统，仅限同机可信用户；Host、Origin 和客户端地址检查提供基础本机防护，不用于多用户或公网环境。
- 模型调用、预算预留/拦截、未知扣费对账尚未实现；未提供可触发付费的 API。
- 不使用 Docker 卷删除命令。备份需停止写入与 Worker，使用 `pg_dump` 备份数据库并同步复制整个 data 目录，在独立数据库恢复并校验哈希后再切换。自动备份/恢复演练留待后续验收。

## 许可证

依赖初步审核与限制见 [LICENSE_REVIEW.md](docs/LICENSE_REVIEW.md)。本项目未决定源码对外授权协议；这不替代依赖各自许可。FFmpeg 采用外部进程调用且不随项目分发，商用分发前应审查具体构建、通知义务与编码专利。

已配置完成时，也可在根目录运行 `powershell -ExecutionPolicy Bypass -File scripts/start.ps1` 隐藏启动三个进程。日志和 PID 存于 `data/runtime`；如需关闭，先核对记录 PID 的实际命令行再停止对应进程。脚本遇到端口占用会退出，不终止其他服务。停止后确认记录中进程均已退出，再移除该进程记录以便重新启动。
