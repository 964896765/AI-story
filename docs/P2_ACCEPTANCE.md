# P2 视频剪辑与成片导出验收

日期：2026-10-28，Asia/Shanghai。基线：`master` / `d7de6fd`；开始时工作区干净。已阅读 README、P1 验收和现有源码，未发现项目级 AGENTS.md。沿用现有 Vue/FastAPI/PostgreSQL、资产、任务和事件表，没有重建工程、修改其他项目或新增第三方依赖。

验收状态：本轮明确实现的 P2 范围通过；后端最终 **37 passed、0 skipped、1条上游弃用提示**，前端类型检查/构建与真实HTTP、浏览器链路通过。下面列明的扩展能力仍未完成，不计入通过范围。

## 实施范围

|能力|实现|
|---|---|
|视频裁剪|开始秒数、结束秒数或时长；有限数值/范围校验；超范围失败|
|画幅与分辨率|原画幅、9:16、16:9、1:1；居中 crop、等比 fit、留边 pad；源尺寸或短边 720/1080/1440/2160；偶数尺寸|
|编码与方向|MP4/MKV，H.264 CRF 默认18 / AAC 192k；源尺寸与帧率默认保留；旋转和 SAR 归一化；HDR/高位深明确拒绝，避免静默转换成8-bit|
|字幕|上传 UTF-8 SRT、格式验证、固定受控文件名烧录；字幕时间以裁剪后片段起点为0|
|音轨|保留、替换或移除；0–4倍音量；无原音轨保持无音轨；替换音轨短则补静音、长则截断|
|队列|复用持久化任务；完整参数/输入快照；同一数据库的所有Worker并发1；领取与更新带所有权校验|
|真实状态|inspecting → encoding → validating → publishing → succeeded；编码百分比来自 FFmpeg out_time_us，验证和发布之前不写100%；保存本次尝试耗时、错误、事件|
|取消/重试|排队立即取消，运行剪辑终止 FFmpeg；失败或取消可重试，递增尝试目录；已发布成功与取消竞争时保留成功成片|
|崩溃恢复|30秒租约、运行时续租；累计尝试不足3次的中断剪辑重新排队；成片已发布但数据库未提交时校验清单与成片后复用|
|交付|独立临时文件；成功退出后再用 ffprobe 验证视频流、音轨、时长、分辨率和旋转；同卷 no-clobber 原子发布；预览、Range、附件下载|

## 实际验证

- 后端完整测试结果和用例数量见 `p2-backend-tests.xml`，无 SQLite 替代：真实 PostgreSQL `story_test`，使用 FFmpeg 自行生成的音视频与 SRT。覆盖原有 P1、时间/画幅/路径校验、真实转码、字幕像素差异、短音轨补齐、旋转、无音轨、无效输入、缺失字幕、排队/运行取消、重试、磁盘不足、错误编码器、缺失执行文件、超时、输出不可解析或时长错误时拒绝发布。
- 实际终止独立 Windows Worker：等待编码进程已创建临时输出，再强制结束 Worker；验证 Job Object 清理 FFmpeg、文件不再被编码进程占用；新进程在过期租约后完成 attempt=2。测试中将租约设为过去时间以缩短等待，生产仍按真实30秒租约运行。
- 崩溃发布对账测试：模拟文件已发布、DB尚未完成，验证恢复使用同一成片且哈希不变，没有重复输出。
- 真实 HTTP 全链路：前端代理 → 导入自有视频与SRT → 重复提交同键 → 两项后台任务 → 两条实际成片；720×1280 / 1.5秒 / 有音轨，360×360 / 2秒 / 无音轨。磁盘文件存在、ffprobe可解析；Range预览206、附件下载200。证据 `p2-http-acceptance.json`。测试素材和项目明确标为验收内容。
- 浏览器：使用本机已安装 Chrome 的独立临时配置，真实表单选择素材、设置参数、提交任务、重复提交去重、查看队列、成片解码播放；未捕获 JS异常。证据 `p2-browser-acceptance.json`、`p2-editor.png`、`p2-output.png`。没有下载浏览器或模型。
- 前端 `npm run build`：Vue/TypeScript 类型检查与 Vite 生产构建通过。
- 在独立空测试库实际执行 `alembic downgrade 0001` → `upgrade head` → `check`，升级/回退成功，无模型差异。正式库保持0002，原有P1数据与文件保留。
- 已有render任务的降级请求会被明确拒绝；自动化验证拒绝后迁移版本仍为0002，没有部分降级。
- 保留1条上游 Starlette TestClient 的 httpx弃用提示；未隐藏，不影响当前通过断言。

复现：按 README 启动；设置 `TEST_DATABASE_URL` 指向独立可丢弃 PostgreSQL 后运行 `python scripts/integration.py`；实机 HTTP 验收运行 `python scripts/p2_smoke.py`；浏览器验收运行 `node --experimental-websocket scripts/browser-p2.mjs`。后两项会增加明确标识的真实测试任务，不虚构成功状态。

## 本轮文件清单

新增：

- `backend/app/render.py`、`backend/app/process_guard.py`。
- `backend/migrations/versions/0002_render_tasks.py`。
- `backend/tests/test_render_unit.py`、`test_render_postgres.py`、`test_worker_crash.py`。
- `frontend/src/VideoEditor.vue`。
- `scripts/p2_smoke.py`、`scripts/browser-p2.mjs`。
- 本文、`docs/p2-backend-tests.xml`、`p2-http-acceptance.json`、`p2-browser-acceptance.json`、`p2-editor.png`、`p2-output.png`。

修改：

- `backend/app/main.py`：SRT、render提交、幂等参数比对、取消、重试和输出API，健康版本0002。
- `backend/app/models.py`：任务生命周期字段与约束。
- `backend/app/worker.py`：全局锁、续租、阶段进度、恢复、所有权校验。
- `backend/app/storage.py`：SRT独立上传大小限制。
- `frontend/src/App.vue`、`style.css`：真实任务控制、成片列表与预览。
- `README.md`、`docs/ACCEPTANCE.md`、`ARCHITECTURE.md`、`LICENSE_REVIEW.md`。

本地忽略产物：`.env`、data中的原始素材、尝试日志/临时文件、输出、验收浏览器配置与服务PID记录；没有提交密钥或视频二进制。截图是UI验收证据。

## 已知边界与未完成项

- 本轮是单素材批量剪辑引擎，不含多素材时间线拼接、转场、模板库、封面生成；这些不标记完成。
- 画幅裁切为居中策略；没有人物跟踪或自定义裁切区域。fit保持内容比例，不保证固定画布。
- 仅SDR 8-bit输出；HDR、高位深、特殊色彩管理和无损音轨透传未实现。默认高画质重编码不是逐比特无损，磁盘使用可能增加。
- 字幕仅UTF-8 SRT，烧录字体使用本机字体；没有字幕编辑器/字体管理/逐字动画。超过片段时长的字幕不自动修正。
- 输出验证属于技术元数据检查，不等于全帧损坏扫描、黑帧/响度/内容审核。
- 运行取消通常约0.5秒；FFmpeg结束兜底5秒，正在阻塞的ffprobe最长60秒。编码总超时6小时；不是实时硬截止系统。
- Windows Job Object保护已实测，其他操作系统的父进程崩溃清理没有验收；当前面向Windows，不宣称跨平台生产就绪。
- 原子发布要求同一存储卷支持硬链接，当前NTFS已验证；没有提供不支持硬链接文件系统的替代路径。
- 中断恢复重新编码整项任务，不做帧级续算；历史尝试日志保留，但尚无日志自动轮转、临时文件回收、全局磁盘配额或心跳管理界面。
- 浏览器批次幂等键在当前标签页 sessionStorage 保存；新标签页/主动新批次会创建新任务。批量提交逐项落库，部分失败保留已接收任务，可同键再次提交。
- 没有新增付费API、模型、部署、平台采集或发布；成本账本仍只记录实际已入账API费用，不把本机处理声称为零总成本。

## 启动与回滚

当前服务继续使用前端 http://127.0.0.1:15173 和后端 http://127.0.0.1:18000，PostgreSQL仅绑定本机。启动步骤见 README；升级时先停止本项目 API/Worker，再迁移至0002并重新启动，避免旧 Worker领取新任务。

回滚前停止提交，等待正在执行任务完成或请求取消并确认终态；核对 `data/runtime/processes.json` 中本项目命令行后停止API/Worker，不按端口杀其他服务。备份数据库与data。保留所有originals、outputs和尝试日志。

首选在0002数据库上修复或恢复同版本备份，不直接运行P1 Worker。迁移降级会检查render任务：只要存在任何render记录就拒绝降级，防止P1把剪辑任务当解析任务重试。仅在没有render记录的库中可执行 `alembic downgrade 0001`（移除P2字段、将cancelled转failed），再回退代码至d7de6fd；测试库的此路径已实测。已有P2业务数据时，要退回P1必须在独立数据库恢复升级前备份，并保留原P2库与文件供后续迁移，不能直接删除任务绕过保护。不要运行`downgrade base`或`docker compose down -v`清空业务数据。
