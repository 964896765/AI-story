# P14 本机发布、安全与恢复验收

基线为 P13 提交 `d57192a`。P14 验收于 2026-11-19 在 Windows、本机 PostgreSQL、独立 Worker、FFmpeg 和已安装 Chrome 环境执行。

## 实际实现与数据库

- 工作台按需载入工作区。最近任务使用分页，已有完整列表 API 继续可用。资产和费用摘要在短间隔内复用，手动刷新重新读取。
- “运行诊断”读取 PostgreSQL 实际任务状态、历史尝试、项目和素材计数、磁盘空间及 Worker 心跳。诊断按 Worker 状态与最后心跳判定在线。
- 后端为请求附加追踪 ID，拦截跨站写请求及声明长度超限的载荷。存储键拦截越界路径、Windows 设备名、NTFS 数据流和符号链接或 junction。
- 迁移 `0013_queue_indexes.py` 为任务查询增加 `(project_id, created_at DESC, id)` 和 `(status, next_run_at, created_at, id)` 索引。旧项目、媒体、任务和版本沿用原有表结构。
- `start.ps1 -Production` 在本机回环端口启动已构建前端，归档上次运行日志。`check_release.ps1` 封装类型检查、生产构建、独立 PostgreSQL 迁移、后端测试与 Chrome 验证。`package_local.ps1` 从已提交版本归档本机源码。

## 实测

- 独立 PostgreSQL 从空库升级到 0013。Alembic 模型比对无差异，后端 **120 项通过，0 失败，0 跳过**，保留 1 条 Starlette/httpx 上游弃用提示。 [后端 JUnit](p14-backend-tests.xml)
- 生产构建通过。在同一隔离工作台依次跑通 P5–P14 十条浏览器流程，覆盖改编版本、媒体解析与采纳、分镜、运镜、双角色配音、时间轴、分集返工、权利与交付、运营和诊断。全链路 Chrome 首轮发现 P6 用例在浏览器刷新证据前读取了快照，改为等待界面同步八项结果，随后通过。Chrome 还验证了 Tab/Enter 进入运行诊断、触发按需载入、跨站写被拒绝，无 JavaScript 错误。 [浏览器总回归](p14-browser-regression.json) · [诊断浏览器](p14-browser-acceptance.json) · [实际截图](p14-system.png)
- P13 首载 JS 构建结果为 249.42 kB（gzip 80.53 kB），P14 为 91.28 kB（gzip 36.01 kB）。退出的 Worker 在线判定与队列一致，专项断言覆盖刚停止仍有新心跳的记录。
- FFmpeg 自制样本生成三集，每集 30 秒。Worker 完成多轨成片、三集技术质检和授权交付，重新下载 ZIP 并验证清单、文件 SHA-256、三集时长。从提交整剧生产到校验 ZIP 用时 14.094 秒，有效输出共 90 秒，ZIP 为 12,801,275 字节。样本使用小尺寸合成内容。独立全量同时回归 20 集短样本的 40 个渲染与质检步骤。实际外部模型费用为 0，未采集电费、人工和授权的单位成本。 [后端 JUnit](p14-backend-tests.xml) · [P11 样本](P11_ACCEPTANCE.md)
- npm 审计初次发现 3 条中等级记录，涉及开发依赖的 `minimatch`。升级 `vue-tsc` 锁定版本后复扫合计 0。PyPI 对 35 个锁定包逐版本检查，修补 `opentelemetry-api` 后 0 条活跃公告、0 个无法检查的包。`pip check` 无依赖冲突。扫描覆盖锁文件和扫描时公开公告。 [npm 复扫](p14-npm-audit.json) · [PyPI 复扫](p14-python-audit.json) · [许可证](LICENSE_REVIEW.md)
- 升级前在停写窗口备份 PostgreSQL 和关联存储。在独立库和独立目录核对 **7 个项目、13 条素材、115 个文件**，复验恢复后的 HTTP 项目、素材及 Range 206。完成 0012→0013→0012→0013 演练，随后本机数据库实际升到 0013。API、Worker 和前端生产构建在本机就绪，真实预算为 0。 [恢复与迁移](p14-backup-migration-acceptance.json) · [本机就绪](p14-local-release.json)

## 文件与复验

- 后端及数据库：`main.py`、`storage.py`、`system_console.py`、`models.py`、`0013_queue_indexes.py`、`test_system_release.py`、`requirements.lock`。
- 前端：`App.vue`、`SystemStudio.vue`、`package.json`、`package-lock.json`。
- 运行与验收：`start.ps1`、`check_release.ps1`、`isolated_regression.py`、`browser-p6.mjs`、`browser-p11.mjs`、`browser-p14.mjs`、`p6_recovery_check.py`、`audit_python.py` 和 `package_local.ps1`。

```powershell
& ./scripts/check_release.ps1 -ProductionBrowser
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --browser-only --all-browsers
& ./.venv/Scripts/python.exe scripts/p6_recovery_check.py --stage p14 --upgrade
& ./scripts/start.ps1 -Production
& ./scripts/package_local.ps1
```

## 限制、回滚与后续

- 本机发布路径按可信本机用户验证。缺少长度头的流式请求、重解析点检查与并发文件替换之间的边界、长时间日志轮转、解码器隔离、多用户权限和发行环境安全仍需进一步验证。跨系统及托管 CI 尚无执行记录。
- 性能结果取自 16 逻辑 CPU 的一台 Windows 机器。商业长剧、GPU 容量、峰值内存、真实供应商账单和不同画质的有效成片成本需独立测试。
- 回滚时停止项目写入，另存当前数据库和文件，然后将 0012 快照恢复到独立数据库及目录，确认一致后切换至 P13 的 `d57192a` 和对应配置。保留 0013 数据及本次升级后文件。本机快照目录记录于恢复证据。
- 后续可独立补齐高级时间轴交互、镜头级增量与部分感知模型接入。对外模型与算力联调需要供应商、许可、限额和输入授权。实际发行、托管发布和商业分发取决于各自所需的凭证与许可。 [能力矩阵](CAPABILITY_MATRIX.md) · [运行手册](PRODUCTION_RUNBOOK.md)
